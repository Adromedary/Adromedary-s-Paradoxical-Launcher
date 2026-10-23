"""Shared look and building blocks for the app's pages.

Sizes: customtkinter scales its own widgets (and their padding, wrap widths, place() coordinates)
by the Windows display scale. Plain Tk widgets (Treeview, Text, PanedWindow) work in real pixels.
`px()` turns a design size into real pixels and `units()` turns real pixels back, so the two kinds
of widget always agree, at 100 % as well as 125 / 150 / 200 %.
"""
import math
import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk

import glyphs

APP_NAME, APP_VERSION, AUTHOR = "Adromedary's Paradoxical Launcher", "2.0", "Adromedary"
APP_SHORT = "Paradoxical Launcher"
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))

# ------------------------------------------------------------------ colours: (light theme, dark theme)
BG, CARD = ("#eceff5", "#0d1117"), ("#ffffff", "#161b24")
CARD_HI, BORDER = ("#f6f8fc", "#1d2430"), ("#d7dde8", "#29313f")
SURFACE = ("#ffffff", "#131821")              # the app bar and status bar
SHADOW = ("#dfe4ee", "#080b10")               # a hairline under raised surfaces
ACCENT, ACCENT_HI = ("#2563d9", "#3d8bfd"), ("#1f55bd", "#5a9dff")
TEXT, MUTED = ("#151c2a", "#e6eaf2"), ("#5d6779", "#8e97ab")
FAINT = ("#8a93a5", "#5f6879")
OK, TEAL = ("#13865a", "#34c98b"), ("#0b8a80", "#2dd4bf")
WARN, ERR = ("#b26a00", "#f2a93b"), ("#cf2f3b", "#ff5d6c")
INFO = ("#6a5acd", "#a99cf5")                 # quiet: "made for another game version"
CRIT = ("#c92a2a", "#ff6b6b")
# tinted backgrounds for pills, banners and summary tiles
ACCENT_SOFT, OK_SOFT = ("#e4ecfd", "#16233d"), ("#ddf4e8", "#11291f")
WARN_SOFT, ERR_SOFT = ("#fdf0d8", "#2e2412"), ("#fde3e5", "#341a1e")
INFO_SOFT, TEAL_SOFT = ("#ebe8fd", "#211d3d"), ("#daf3f0", "#0f2a28")
MUTED_SOFT = ("#e2e6ee", "#232a37")
SEV_COLOR = {"critical": CRIT, "high": WARN, "medium": ("#9c6500", "#ffd43b"), "low": MUTED, "info": TEAL}
SEV_SOFT = {"critical": ERR_SOFT, "high": WARN_SOFT, "medium": ("#fbf3d4", "#2c2610"), "low": MUTED_SOFT,
            "info": TEAL_SOFT}
# Text symbols are limited to ones every Windows font fallback draws (no colour-emoji code points).
SEV_ICON = {"critical": "⊘", "high": "⚠", "medium": "◆", "low": "•", "info": "✓"}
SEV_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "info": "Info"}
BANNER, DANGER_HOVER = WARN_SOFT, ("#f6d3d6", "#4a2228")
SEL = ("#d9e5fd", "#1f3a66")                  # selected rows
ROW_ALT = ("#f8f9fc", "#191f2a")              # every other row
PLAY, PLAY_HI = ("#13865a", "#1f9d6b"), ("#0f774f", "#27b47c")
TAB_ON, TAB_ON_HI = ("#d6e3fd", "#24406f"), ("#c6d8fc", "#2c4d85")
THEMES = ["System", "Light", "Dark"]
FONT = "Segoe UI" if sys.platform.startswith("win") else "DejaVu Sans"
MONO = "Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono"
WARN_ICON, VER_ICON, UPD_ICON, MISS_ICON = "⚠", "○", "↻", "✗"
WHITE = ("#ffffff", "#ffffff")
PALETTES = ["Classic", "Colorful"]


def _saved_palette():
    """The palette is chosen before any widget exists (Tk widgets keep the colours they were made with),
    so it's read from the settings file here; changing it takes a restart."""
    env = os.environ.get("PMC_PALETTE")
    if env:
        return env
    try:
        import json
        with open(os.path.join(APP_DIR, "settings.json"), encoding="utf-8") as f:
            v = json.load(f).get("palette", "Classic")
        return v if v in PALETTES else "Classic"
    except Exception:
        return "Classic"


PALETTE = _saved_palette()
COLORFUL = PALETTE == "Colorful"
# every main tab has its own colour family in the Colorful palette: (strong, soft)
TAB_COLORS = {
    "Browse": (("#2458c9", "#6ea2ff"), ("#e1e9fb", "#172440")),
    "Catch": (("#0b8276", "#34d3bd"), ("#d6efe9", "#0f2b28")),
    "Library": (("#7b35b5", "#c09bff"), ("#eee0f8", "#2b1f40")),
    "Playsets": (("#1c8049", "#56d98c"), ("#dcefdf", "#122a1d")),
    "Conflicts": (("#ad5f08", "#f7b94a"), ("#f8e6c8", "#30230f")),
    "Crashes": (("#b8263a", "#ff7385"), ("#f8dde0", "#361a20")),
}
if COLORFUL:
    # warm parchment and deep royal tones (light), candle-lit violet night (dark)
    BG, CARD = ("#ece2cf", "#14101b"), ("#fffaf1", "#1e1727")
    CARD_HI, BORDER = ("#f6ecda", "#271e32"), ("#d3be98", "#43355a")
    SURFACE = ("#f9f1e2", "#1a1422")
    SHADOW = ("#c9b38a", "#07050a")
    ACCENT, ACCENT_HI = ("#7333a8", "#b98cff"), ("#5f2a8c", "#cba6ff")
    TEXT, MUTED = ("#2a1f14", "#f3eadb"), ("#6b5a45", "#b8a891")
    FAINT = ("#9a8970", "#7d705f")
    ACCENT_SOFT = ("#ecdcf6", "#2c1f3f")
    OK_SOFT, WARN_SOFT = ("#dcecd4", "#132a1d"), ("#f7e2bd", "#30230f")
    ERR_SOFT, INFO_SOFT = ("#f6d8d6", "#371b22"), ("#e6dcf6", "#241d3e")
    TEAL_SOFT, MUTED_SOFT = ("#d4ece5", "#102b28"), ("#e6d9c2", "#2a2234")
    SEV_SOFT = {"critical": ERR_SOFT, "high": WARN_SOFT, "medium": ("#f5e8c4", "#2e2711"), "low": MUTED_SOFT,
                "info": TEAL_SOFT}
    BANNER, DANGER_HOVER = WARN_SOFT, ("#f1cdcf", "#4a2228")
    SEL = ("#e6d2f4", "#3b2a5a")
    ROW_ALT = ("#faf2e4", "#221a2d")
    TAB_ON, TAB_ON_HI = ("#e6d2f4", "#3b2a5a"), ("#dcc3f0", "#47326b")


# ------------------------------------------------------------------ a guard for customtkinter's scrollbar
def _guard_ctk_scrollbar():
    """At fractional display scales (125 %, 150 %...) a stretched CTkScrollbar can see its height round
    between two pixel sizes forever (894 <-> 895 px): every redraw forces a layout pass that reports the
    other size, and the app freezes. Ignore one-pixel rounding jitter, and never redraw re-entrantly."""
    try:
        from customtkinter.windows.widgets import ctk_scrollbar as cs
    except Exception:
        return
    cls = cs.CTkScrollbar
    if getattr(cls, "_pmc_guarded", False):
        return
    draw = cls._draw

    def _draw(self, no_color_updates=False):
        if getattr(self, "_pmc_drawing", False):
            return
        self._pmc_drawing = True
        try:
            draw(self, no_color_updates)
        finally:
            self._pmc_drawing = False

    def _update_dimensions_event(self, event):
        w = self._reverse_widget_scaling(event.width)
        h = self._reverse_widget_scaling(event.height)
        if abs(self._current_width - w) > 1 or abs(self._current_height - h) > 1:
            self._current_width, self._current_height = w, h
            self._draw(no_color_updates=True)

    cls._draw = _draw
    cls._update_dimensions_event = _update_dimensions_event
    cls._pmc_guarded = True


_guard_ctk_scrollbar()


# ------------------------------------------------------------------ scale, fonts, colours
def scale():
    """The display scale customtkinter uses (1.0 at 100 %, 1.5 at 150 %...)."""
    try:
        return float(ctk.ScalingTracker.get_widget_scaling(_root[0])) if _root else 1.0
    except Exception:
        return 1.0


_root = []


def set_root(root):
    _root[:] = [root]


def px(n):
    """A design size in real pixels."""
    return int(round(n * scale()))


def units(pixels):
    """Real pixels back to the design units customtkinter widgets expect."""
    return pixels / scale()


_fonts = {}


def font(size, weight="normal"):
    """A shared CTkFont (created once per size and weight)."""
    key = (size, weight)
    f = _fonts.get(key)
    if f is None:
        f = _fonts[key] = ctk.CTkFont(FONT, size, weight)
    return f


_tkfonts = {}


def tk_font(size, weight="normal", family=None):
    """A Tk font for plain Tk widgets, sized like the CTk fonts (in pixels, at the current scale)."""
    key = (family or FONT, size, weight, round(scale(), 2))
    f = _tkfonts.get(key)
    if f is None:
        f = _tkfonts[key] = tkfont.Font(family=family or FONT, size=-px(size), weight=weight)
    return f


def fit_geometry(win, w, h, parent=None):
    """Size a window (design units) to fit the screen, centred on its parent or the screen."""
    try:
        sw, sh = units(win.winfo_screenwidth()), units(win.winfo_screenheight())
    except Exception:
        sw, sh = 1920, 1080
    w, h = int(min(w, sw * 0.94)), int(min(h, sh * 0.88))
    if parent is not None and parent.winfo_viewable():
        x = units(parent.winfo_rootx()) + (units(parent.winfo_width()) - w) / 2
        y = units(parent.winfo_rooty()) + (units(parent.winfo_height()) - h) / 3
    else:
        x, y = (sw - w) / 2, (sh - h) / 3
    win.geometry(f"{w}x{h}+{int(max(0, x))}+{int(max(0, y))}")


def pick(color):
    """The current theme's half of a (light, dark) colour."""
    if isinstance(color, (tuple, list)):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color


def open_folder(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


# ------------------------------------------------------------------ icons and buttons
_icons = {}


def icon(name, size=16, color=None):
    """A drawn interface icon as a CTkImage that follows the light/dark theme (None without Pillow)."""
    color = color or TEXT
    if not glyphs.available():
        return None
    key = (name, size, tuple(color) if isinstance(color, (list, tuple)) else color)
    if key not in _icons:
        light, dark = (color if isinstance(color, (list, tuple)) else (color, color))
        _icons[key] = ctk.CTkImage(light_image=glyphs.draw(name, size * 3, light),
                                   dark_image=glyphs.draw(name, size * 3, dark), size=(size, size))
    return _icons[key]


def clearable(entry, on_clear=None):
    """A small x at the end of a search box that empties it at once. It shows only while there's text."""
    b = ctk.CTkButton(entry, text="", image=icon("close", 11, MUTED), width=20, height=20, corner_radius=10,
                      fg_color="transparent", hover_color=BORDER, border_width=0)

    def update(e=None):
        try:
            has = bool(entry.get())
        except Exception:
            return
        if has and not b.winfo_ismapped():
            b.place(relx=1.0, rely=0.5, x=-5, anchor="e")
        elif not has and b.winfo_ismapped():
            b.place_forget()

    def clear():
        entry.delete(0, "end")
        entry.focus_set()
        update()
        if on_clear:
            on_clear()
    b.configure(command=clear)
    Tooltip(b, "Clear")
    # keep typed text clear of the x
    grid = entry._create_grid

    def make_room():
        grid()
        try:
            left = entry._entry.grid_info().get("padx", 0)
            left = int(left[0] if isinstance(left, (tuple, list)) else str(left).split()[0])
            entry._entry.grid_configure(padx=(left, left + px(20)))
        except Exception:
            pass
    entry._create_grid = make_room
    make_room()
    for ev in ("<KeyRelease>", "<FocusIn>", "<FocusOut>", "<<Paste>>", "<<Cut>>"):
        entry.bind(ev, lambda e: entry.after_idle(update), add="+")
    for name in ("insert", "delete"):                 # text put in or taken out by the app
        orig = getattr(entry, name)

        def wrapped(*a, _orig=orig, **k):
            r = _orig(*a, **k)
            entry.after_idle(update)
            return r
        setattr(entry, name, wrapped)
    entry._clear_btn = b
    update()
    return b


def button(parent, text, command, primary=False, danger=False, width=None, height=30, icon_name=None,
           icon_size=15, tip=None, **kw):
    """The app's button looks: filled blue (primary), quiet card-coloured, or red-tinted (danger),
    with an optional icon and hover tip."""
    opts = dict(text=text, command=command, height=height, corner_radius=8,
                font=font(12, "bold" if primary else "normal"))
    if width:
        opts["width"] = width
    if icon_name:
        img = icon(icon_name, icon_size, WHITE if primary else (ERR if danger else TEXT))
        if img is not None:
            opts.update(image=img, compound="left")
            if not text:
                opts.setdefault("width", height)
    if primary:
        opts.update(fg_color=ACCENT, hover_color=ACCENT_HI, text_color="white", border_width=0,
                    text_color_disabled=("#c9d8f7", "#7d9bd2"))
    else:
        opts.update(fg_color=CARD, hover_color=DANGER_HOVER if danger else CARD_HI,
                    text_color=ERR if danger else TEXT, border_width=1, border_color=BORDER, text_color_disabled=FAINT)
    opts.update(kw)
    b = ctk.CTkButton(parent, **opts)
    if tip:
        Tooltip(b, tip)
    return b


def style_button(b, kind="normal", icon_name=None, icon_size=15):
    """Restyle an existing button (pools of buttons are reused instead of rebuilt)."""
    if kind == "primary":
        b.configure(fg_color=ACCENT, hover_color=ACCENT_HI, text_color="white", border_width=0,
                    font=font(12, "bold"))
    else:
        b.configure(fg_color=CARD, hover_color=DANGER_HOVER if kind == "danger" else CARD_HI,
                    text_color=ERR if kind == "danger" else TEXT, border_width=1, border_color=BORDER,
                    font=font(12))
    img = icon(icon_name, icon_size, WHITE if kind == "primary" else (ERR if kind == "danger" else TEXT)) \
        if icon_name else None
    b.configure(image=img)


def card(parent, **kw):
    kw.setdefault("fg_color", CARD)
    return ctk.CTkFrame(parent, corner_radius=12, border_width=1, border_color=BORDER, **kw)


def pill(parent, text, color=ACCENT, soft=ACCENT_SOFT, size=11, icon_name=None):
    """A small tinted label: coloured text on a soft background of the same hue."""
    return ctk.CTkLabel(parent, text=text, text_color=color, fg_color=soft, corner_radius=9, height=22,
                        font=font(size, "bold"), padx=8,
                        image=icon(icon_name, 13, color) if icon_name else None, compound="left")


# ------------------------------------------------------------------ hover tips
class Tooltip:
    """A small note that appears when the pointer rests on a widget."""

    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip, self.job = None, None
        for w in self._targets(widget):
            w.bind("<Enter>", self._enter, add="+")
            w.bind("<Leave>", self._leave, add="+")
            w.bind("<ButtonPress>", self._leave, add="+")

    @staticmethod
    def _targets(widget):
        out = [widget]
        for name in ("_canvas", "_text_label", "_image_label", "_label"):
            w = getattr(widget, name, None)
            if w is not None:
                out.append(w)
        return out

    def _enter(self, e=None):
        self._cancel()
        self.job = self.widget.after(self.delay, self._show)

    def _leave(self, e=None):
        self._cancel()
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def _cancel(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self):
        if self.tip is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(6)
        t = tk.Toplevel(self.widget)
        t.wm_overrideredirect(True)
        try:
            t.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = tk.Frame(t, bg=pick(BORDER), bd=0)
        frame.pack()
        lbl = tk.Label(frame, text=self.text, bg=pick(SURFACE), fg=pick(TEXT), font=tk_font(11), justify="left",
                       wraplength=px(300), padx=px(9), pady=px(5))
        lbl.pack(padx=1, pady=1)
        t.update_idletasks()
        w = t.winfo_reqwidth()
        sx = self.widget.winfo_screenwidth()
        t.geometry(f"+{max(4, min(x - w // 2, sx - w - 4))}+{y}")
        self.tip = t


# ------------------------------------------------------------------ ttk.Treeview in the app's colours
def style_trees(root):
    """(Re)style every Treeview for the current light/dark mode. Called again when the theme changes."""
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    bg, fg, head, line, sel = pick(CARD), pick(TEXT), pick(CARD_HI), pick(BORDER), pick(SEL)
    body, bold, small = tk_font(13), tk_font(12, "bold"), tk_font(12)
    for name, rh in (("PMC.Treeview", 28), ("PMC.Big.Treeview", 42)):
        s.configure(name, background=bg, fieldbackground=bg, foreground=fg, rowheight=px(rh),
                    borderwidth=0, relief="flat", font=body)
        s.map(name, background=[("selected", sel)], foreground=[("selected", fg)])
        s.configure(name + ".Heading", background=head, foreground=pick(MUTED), relief="flat",
                    borderwidth=0, font=bold, padding=(px(6), px(5)))
        s.map(name + ".Heading", background=[("active", line)], foreground=[("active", fg)])
        s.layout(name, [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("PMC.Item", font=small)
    # a slim scrollbar in the app's colours (no arrows)
    s.layout("PMC.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("PMC.Vertical.TScrollbar", troughcolor=bg, background=pick(BORDER), bordercolor=bg,
                lightcolor=pick(BORDER), darkcolor=pick(BORDER), relief="flat", borderwidth=0, gripcount=0,
                arrowsize=px(10), width=px(10))
    s.map("PMC.Vertical.TScrollbar", background=[("active", pick(FAINT)), ("pressed", pick(MUTED))],
          lightcolor=[("active", pick(FAINT))], darkcolor=[("active", pick(FAINT))])


def tree_tags(tree):
    tree.tag_configure("conflict", foreground=pick(WARN))
    tree.tag_configure("missing", foreground=pick(ERR))
    tree.tag_configure("muted", foreground=pick(MUTED))
    tree.tag_configure("version", foreground=pick(INFO))
    tree.tag_configure("update", foreground=pick(ACCENT))
    tree.tag_configure("ok", foreground=pick(OK))
    tree.tag_configure("group", foreground=pick(WARN), font=tk_font(13, "bold"))
    tree.tag_configure("bold", font=tk_font(13, "bold"))
    for sev, col in SEV_COLOR.items():
        tree.tag_configure(sev, foreground=pick(col))
    tree.tag_configure("odd", background=pick(ROW_ALT))


COLUMNS = {"cfg": None, "save": None}     # set by the app: where dragged column widths are kept


class Tree(ctk.CTkFrame):
    """A ttk.Treeview with a themed scrollbar. columns: [(id, heading, width, anchor, stretch)].
    Widths are design units (scaled to the display). With a key, widths you drag are remembered."""

    def __init__(self, parent, columns, show_tree=False, selectmode="extended", height=10, big=False,
                 image_width=0, main=None, drop=(), min_main=200, key=None):
        """main: the column that gets the spare width; drop: columns hidden (in this order) when the list
        gets too narrow for `main` to keep min_main, and shown again when there's room."""
        super().__init__(parent, fg_color=CARD, corner_radius=10, border_width=1, border_color=BORDER, height=40)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        ids = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=ids, show=("tree headings" if show_tree else "headings"),
                                 style="PMC.Big.Treeview" if big else "PMC.Treeview", selectmode=selectmode,
                                 height=height)
        self.images = {}             # keep PhotoImages alive (Tk drops them otherwise)
        for cid, head, width, anchor, stretch in columns:
            self.tree.heading(cid, text=head, anchor=anchor)
            self.tree.column(cid, width=px(width), minwidth=px(30), anchor=anchor, stretch=stretch)
        self.show_tree = show_tree
        self.pic_col = bool(image_width)
        if show_tree:
            w = px(image_width or 26)
            self.tree.column("#0", width=w, minwidth=w, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview, style="PMC.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns", padx=(2, 5), pady=8)
        self.tree.configure(yscrollcommand=sb.set)
        tree_tags(self.tree)
        self.cols = {c[0]: c for c in columns}
        self.order = [c[0] for c in columns]
        self.main, self.drop, self.min_main = main, list(drop), min_main
        self.hidden = []
        self._tw = 0
        self.key = key
        self._drag = None
        saved = (COLUMNS["cfg"] or {}).get(key) if key else None
        for cid, w in (saved or {}).items():            # widths you dragged last time (design units)
            if cid in self.cols and not self.cols[cid][4] and isinstance(w, (int, float)) and 24 <= w <= 900:
                c = self.cols[cid]
                self.cols[cid] = (c[0], c[1], int(w), c[3], c[4])
                self.tree.column(cid, width=px(w))
        if main and drop:
            self.tree.bind("<Configure>", self._fit, add="+")
        # Dividers between headings: the edge you drag moves, the column on its left changes size and
        # the one on its right gives or takes the difference (ttk's own handler moves the other edge).
        self.tree.bind("<ButtonPress-1>", self._press, add="+")
        self.tree.bind("<B1-Motion>", self._motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._release, add="+")

    # ---- column dividers
    def _visible(self):
        dc = list(self.tree.cget("displaycolumns"))
        return [c for c in self.order if c in dc] if dc and dc != ["#all"] else list(self.order)

    def _press(self, e):
        if self.tree.identify_region(e.x, e.y) != "separator":
            return None
        cols = self._visible()
        x = int(self.tree.column("#0", "width")) if self.show_tree else 0
        left = None
        if self.show_tree and abs(e.x - x) <= px(6):
            if self.pic_col or not cols:
                return "break"                     # the picture column keeps its size
            self._drag = (e.x, "#0", cols[0], x, int(self.tree.column(cols[0], "width")))
            return "break"
        for c in cols:
            x += int(self.tree.column(c, "width"))
            if abs(e.x - x) <= px(6):
                left = c
                break
        if left is None:
            return "break"
        i = cols.index(left)
        right = cols[i + 1] if i + 1 < len(cols) else (self.main if self.main in cols and self.main != left
                                                        else None)
        if right is None:
            return "break"
        self._drag = (e.x, left, right, int(self.tree.column(left, "width")), int(self.tree.column(right, "width")))
        return "break"

    def _motion(self, e):
        if not self._drag:
            return None
        x0, left, right, wl, wr = self._drag
        lo = px(30)
        d = e.x - x0
        d = max(lo - wl, min(d, wr - lo))
        self.tree.column(left, width=wl + d)
        self.tree.column(right, width=wr - d)
        return "break"

    def _release(self, e):
        if not self._drag:
            return None
        _, left, right, _, _ = self._drag
        self._drag = None
        for cid in (left, right):
            c = self.cols.get(cid)
            if c is None:
                continue
            if not c[4]:
                self.cols[cid] = (c[0], c[1], int(round(units(int(self.tree.column(cid, "width"))))), c[3], c[4])
        self._tw = 0
        if self.key and COLUMNS["cfg"] is not None:
            COLUMNS["cfg"][self.key] = {cid: c[2] for cid, c in self.cols.items() if not c[4]}
            if COLUMNS["save"]:
                COLUMNS["save"]()
        return "break"

    def _fixed(self, visible):
        w = sum(px(self.cols[c][2]) for c in visible if not self.cols[c][4])
        if self.show_tree:
            w += int(self.tree.column("#0", "width"))
        return w

    def _fit(self, e=None):
        width = self.tree.winfo_width()
        if width < 50 or abs(width - self._tw) < 4:
            return
        self._tw = width
        visible = [c for c in self.order if c not in self.hidden]
        changed = False
        need = px(self.min_main)
        while True:
            room = width - self._fixed(visible)
            if room < need:
                nxt = next((c for c in self.drop if c not in self.hidden), None)
                if not nxt:
                    break
                self.hidden.append(nxt)
                visible.remove(nxt)
                changed = True
                continue
            if self.hidden:
                back = self.hidden[-1]
                if room - px(self.cols[back][2]) >= need + px(16):
                    self.hidden.pop()
                    visible = [c for c in self.order if c not in self.hidden]
                    changed = True
                    continue
            break
        if changed:
            self.tree.configure(displaycolumns=visible)
        # never wider than the list: the stretchy columns give up the difference (the last ones stay in view)
        over = self._fixed(visible) + sum(int(self.tree.column(c, "width")) for c in visible if self.cols[c][4]) \
            - width + px(2)
        stretchy = [c for c in visible if self.cols[c][4]]
        if over > 0 and stretchy:
            for c in stretchy:
                w = int(self.tree.column(c, "width"))
                cut = min(over, max(0, w - px(80)))
                if cut:
                    self.tree.column(c, width=w - cut)
                    over -= cut

    def stripe(self, parent=""):
        """Tint every other row (keeps each row's own tags)."""
        t = self.tree
        for i, rid in enumerate(t.get_children(parent)):
            tags = [x for x in t.item(rid, "tags") if x != "odd"]
            if i % 2:
                tags.append("odd")
            t.item(rid, tags=tags)

    def restyle(self):
        tree_tags(self.tree)


# ------------------------------------------------------------------ read-only, copyable text
class CopyableText(ctk.CTkTextbox):
    """Read-only text you can select and copy (Ctrl+C / Ctrl+A), unlike a label."""

    NAV = {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next", "Shift_L", "Shift_R",
           "Control_L", "Control_R"}

    def __init__(self, master, text="", height=120, **kw):
        super().__init__(master, height=height, fg_color=BG, border_width=1, border_color=BORDER,
                         text_color=MUTED, font=ctk.CTkFont(MONO, 11), wrap="word", **kw)
        self.set(text)
        tb = self._textbox
        tb.bind("<Key>", self._key)
        for ev in ("<<Paste>>", "<<Cut>>", "<<Clear>>"):
            tb.bind(ev, lambda e: "break")
        tb.bind("<Control-a>", self._select_all)
        tb.bind("<Control-A>", self._select_all)

    def set(self, text):
        self.delete("1.0", "end")
        self.insert("1.0", text)

    def _key(self, e):
        if e.state & 0x4 and e.keysym.lower() in ("c", "insert", "a"):
            return None
        if e.keysym in self.NAV:
            return None
        return "break"

    def _select_all(self, e=None):
        self._textbox.tag_add("sel", "1.0", "end-1c")
        return "break"


# ------------------------------------------------------------------ one-line notification strip
BANNER_KINDS = {  # kind -> (text colour, background, icon)
    "ok": (OK, OK_SOFT, "check"), "info": (ACCENT, ACCENT_SOFT, "info"), "warn": (WARN, WARN_SOFT, "alert"),
    "error": (ERR, ERR_SOFT, "alert"), "muted": (MUTED, MUTED_SOFT, "info"),
}
COLOR_KIND = {}


class Banner(ctk.CTkFrame):
    """Message strip under the tabs: tinted by its kind (done / info / warning / error), with an icon
    and up to two action buttons."""

    def __init__(self, parent):
        super().__init__(parent, fg_color=WARN_SOFT, corner_radius=10, height=40, border_width=1,
                         border_color=WARN_SOFT)
        self.grid_columnconfigure(1, weight=1)
        self.ic = ctk.CTkLabel(self, text="", width=22)
        self.ic.grid(row=0, column=0, padx=(12, 2), pady=6)
        self.label = ctk.CTkLabel(self, text="", text_color=WARN, font=font(12, "bold"), anchor="w",
                                  justify="left", wraplength=900)
        self.label.grid(row=0, column=1, sticky="ew", padx=(4, 8), pady=7)
        self.btns = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.btns.grid(row=0, column=2, padx=(0, 8))
        self.kind = None
        self._ww = 0
        parent.bind("<Configure>", self._wrap, add="+")         # by the window's width, not its own

    def _wrap(self, e):
        if e.widget is not self.master:
            return
        w = int(max(200, units(e.width) - 300))
        if abs(w - self._ww) > 8:
            self._ww = w
            self.label.configure(wraplength=w)

    def show(self, text, actions=(), kind=None, color=None, tone=None):
        """tone: ok / info / warn / error / muted (or derived from the older `color` argument)."""
        for w in self.btns.winfo_children():
            w.destroy()
        self.kind = kind
        if tone is None:
            tone = {OK: "ok", ACCENT: "info", ERR: "error", CRIT: "error", MUTED: "muted"}.get(
                tuple(color) if isinstance(color, list) else color, "warn")
        fg, bg, ic = BANNER_KINDS.get(tone, BANNER_KINDS["warn"])
        self.configure(fg_color=bg, border_color=bg)
        self.ic.configure(image=icon(ic, 17, fg))
        self.label.configure(text=text, text_color=fg)
        for label, cmd in actions:
            button(self.btns, label, cmd, primary=not self.btns.winfo_children(), height=26).pack(side="left", padx=3)
        self.grid()

    def hide(self, kind=None):
        if kind is None or kind == self.kind:
            self.grid_remove()
            self.kind = None


# ------------------------------------------------------------------ pictures
def tk_image(owner, key, pil_image):
    """A Tk PhotoImage for a PIL image, kept alive in owner.images[key]."""
    if pil_image is None:
        return ""
    try:
        from PIL import ImageTk
    except Exception:
        return ""
    store = owner.__dict__.setdefault("images", {})
    if key not in store:
        if len(store) > 1200:
            store.clear()
        store[key] = ImageTk.PhotoImage(pil_image)
    return store[key]


def row_picture(owner, key, path, role, h=32):
    """Thumbnail + role badge for a list row, at the display scale (cached on owner)."""
    import icons
    if not icons.available():
        return ""
    H = px(h)
    return tk_image(owner, ("row", key, role.id, path, H), icons.row_image(path, role, H, px(16), px(4)))


def ctk_image(pil_image, size=None):
    if pil_image is None:
        return None
    size = size or pil_image.size
    return ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=size)


_badges = {}


def badge_image(role, size=16):
    """A role's badge as a CTkImage, made once and kept: a label never points at an image Tk has thrown away."""
    import icons
    key = (getattr(role, "name", str(role)), size)
    if key not in _badges:
        _badges[key] = ctk_image(icons.badge(role, 48), (size, size)) if icons.available() else None
    return _badges[key]


def role_chip(parent, role, text=None, size=16):
    """A small label with the role's badge and name."""
    import icons
    img = ctk_image(icons.badge(role, size * 3), (size, size)) if icons.available() else None
    return ctk.CTkLabel(parent, text=" " + (text or role.name), image=img, compound="left", text_color=TEXT,
                        font=font(11, "bold"), fg_color=CARD_HI, corner_radius=9, height=size + 8, padx=6)


def sev_chip(parent, sev, text=None):
    return pill(parent, f"{SEV_ICON[sev]} {text or SEV_LABEL[sev]}", SEV_COLOR[sev], SEV_SOFT[sev])


# ------------------------------------------------------------------ tab bar with icons and counters
class TabBar(ctk.CTkFrame):
    """The main tabs: icon + name with a coloured underline on the current one, and a counter pill drawn
    inside the tab (no floating labels, so nothing shows behind its rounded corners)."""

    def __init__(self, parent, tabs, command, icons_for=None, bg=SURFACE):
        super().__init__(parent, fg_color="transparent")
        self.command, self.current = command, None
        self.icons_for = icons_for or {}
        self.tabs = {}
        for i, name in enumerate(tabs):
            f = ctk.CTkFrame(self, fg_color="transparent", corner_radius=9, cursor="hand2", width=1, height=1)
            f.grid(row=0, column=i, padx=(0 if i == 0 else 2, 0))
            ic = ctk.CTkLabel(f, text="", image=icon(self.icons_for.get(name, "info"), 17, MUTED), width=20)
            ic.grid(row=0, column=0, padx=(12, 6), pady=(7, 5))
            lbl = ctk.CTkLabel(f, text=name, text_color=MUTED, font=font(13, "bold"))
            lbl.grid(row=0, column=1, pady=(7, 5))
            badge = ctk.CTkLabel(f, text="", height=19, corner_radius=9, fg_color=ACCENT, text_color="white",
                                 font=font(10, "bold"), width=22, padx=5)
            badge.grid(row=0, column=2, padx=(6, 0), pady=(7, 5))
            badge.grid_remove()
            spacer = ctk.CTkFrame(f, fg_color="transparent", width=12, height=1)
            spacer.grid(row=0, column=3)
            bar = ctk.CTkFrame(f, fg_color="transparent", height=3, width=1, corner_radius=2)
            bar.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=(0, 2))
            self.tabs[name] = {"frame": f, "icon": ic, "label": lbl, "badge": badge, "bar": bar}
            for w in (f, ic, lbl, badge, spacer, bar):
                w.bind("<Button-1>", lambda e, n=name: self.command(n))
                w.bind("<Enter>", lambda e, n=name: self._hover(n, True))
                w.bind("<Leave>", lambda e, n=name: self._hover(n, False))

    def _hover(self, name, on):
        if name != self.current:
            self.tabs[name]["frame"].configure(fg_color=CARD_HI if on else "transparent")

    def get(self):
        return self.current

    def colors(self, name):
        """(strong, soft) colours of a tab: its own family in the Colorful palette, the accent otherwise."""
        return TAB_COLORS.get(name, (ACCENT, ACCENT_SOFT)) if COLORFUL else (ACCENT, ACCENT_SOFT)

    def set(self, name):
        self.current = name
        for n, t in self.tabs.items():
            sel = n == name
            strong, soft = self.colors(n)
            t["frame"].configure(fg_color=soft if sel else "transparent")
            t["label"].configure(text_color=strong if sel else MUTED)
            t["icon"].configure(image=icon(self.icons_for.get(n, "info"), 17, strong if (sel or COLORFUL) else MUTED))
            t["bar"].configure(fg_color=strong if sel else "transparent")

    def set_badge(self, name, text, color=None):
        """Small counter inside a tab ('' hides it)."""
        b = self.tabs[name]["badge"]
        if not text:
            b.grid_remove()
            return
        b.configure(text=str(text), fg_color=color or ACCENT)
        b.grid()


class Ribbon(ctk.CTkLabel):
    """Colorful palette: a textured band under the app bar in the current tab's colour (a heraldic lattice
    over a gradient). Redrawn when the window is resized or the tab changes."""
    HEIGHT = 7

    def __init__(self, parent):
        super().__init__(parent, text="", height=self.HEIGHT, fg_color=SURFACE, corner_radius=0)
        self.tab, self._seen_w, self._job = None, 0, None
        self.bind("<Configure>", self._resized, add="+")

    def _resized(self, e):
        if abs(e.width - self._seen_w) > 2:
            self._seen_w = e.width
            if self._job:
                self.after_cancel(self._job)
            self._job = self.after(120, self.draw)

    def set_tab(self, name):
        if name != self.tab:
            self.tab = name
            self.draw()

    @staticmethod
    def texture(w, h, strong, soft):
        from PIL import Image, ImageDraw
        def rgb(c):
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        a, b = rgb(strong), rgb(soft)
        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        for x in range(w):                                  # strong on the left, fading to soft on the right
            t = min(1.0, x / max(1, w * 0.85)) ** 1.6
            d.line([(x, 0), (x, h)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
        over = Image.new("RGBA", (w, h), (0, 0, 0, 0))      # a lattice of small diamonds, lightly
        o = ImageDraw.Draw(over)
        step = max(6, h * 2)
        for x in range(-step, w + step, step):
            o.line([(x, 0), (x + h, h)], fill=(255, 255, 255, 46), width=1)
            o.line([(x + h, 0), (x, h)], fill=(0, 0, 0, 30), width=1)
        img = Image.alpha_composite(img.convert("RGBA"), over)
        ImageDraw.Draw(img).line([(0, h - 1), (w, h - 1)], fill=(0, 0, 0, 40))
        return img

    def draw(self):
        self._job = None
        if not COLORFUL or not self.tab or not glyphs.available():
            return
        w = max(10, self.winfo_width())
        h = max(4, px(self.HEIGHT))
        strong, soft = TAB_COLORS.get(self.tab, (ACCENT, ACCENT_SOFT))
        try:
            self._img = ctk.CTkImage(light_image=self.texture(w, h, strong[0], soft[0]),
                                     dark_image=self.texture(w, h, strong[1], soft[1]),
                                     size=(units(w), self.HEIGHT))
            self.configure(image=self._img)
        except Exception:
            pass


# ------------------------------------------------------------------ resizable splits
class Split(tk.PanedWindow):
    """A draggable divider between panes (lists and their detail panes). Remembers pane sizes.
    Each pane gets an explicit arrow cursor: Tk leaves the divider's resize cursor on the panedwindow
    when the pointer leaves the divider straight into a pane, and every pane would inherit it."""
    instances = []

    def __init__(self, parent, app, key, orient="horizontal"):
        super().__init__(parent, orient=orient, sashwidth=px(8), bd=0, relief="flat", showhandle=False,
                         opaqueresize=False, sashcursor="sb_h_double_arrow" if orient == "horizontal"
                         else "sb_v_double_arrow", bg=pick(BG), borderwidth=0, cursor="arrow")
        self.app, self.key, self.orient = app, key, orient
        self.remember = []                      # (pane name, widget) whose size is saved
        Split.instances.append(self)
        self.bind("<ButtonRelease-1>", lambda e: self.after(50, self._save))
        self.bind("<Leave>", lambda e: self.configure(cursor="arrow"), add="+")

    def add_pane(self, widget, size=None, minsize=120, stretch="always", name=None):
        """size / minsize in design units."""
        try:
            tk.Frame.configure(widget, cursor="arrow")
        except tk.TclError:
            pass
        opts = dict(minsize=px(minsize), stretch=stretch)
        saved = (self.app.cfg.get("panes", {}) or {}).get(f"{self.key}.{name}") if name else None
        if saved and saved < px(minsize):
            saved = None
        size = saved or (px(size) if size else None)
        if size:
            opts["width" if self.orient == "horizontal" else "height"] = int(size)
        self.add(widget, **opts)
        if name:
            self.remember.append((name, widget))

    def _save(self):
        store = self.app.cfg.setdefault("panes", {})
        changed = False
        for name, w in self.remember:
            v = w.winfo_width() if self.orient == "horizontal" else w.winfo_height()
            if v > 20 and store.get(f"{self.key}.{name}") != v:
                store[f"{self.key}.{name}"] = v
                changed = True
        if changed:
            self.app.save()

    def restyle(self):
        try:
            self.configure(bg=pick(BG))
        except tk.TclError:
            pass


def page_frame(parent):
    """A plain frame that lives inside a Split pane (an explicit colour: a Tk pane can't pass on the theme)."""
    return ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)


# ------------------------------------------------------------------ the detail panel
DETAIL_WIDTH = 392          # design units: a 340-wide square picture plus the panel's margins


class RichText(tk.Text):
    """Read-only formatted text for the detail panels: headings, coloured lines, links, small pictures.
    One widget for all of it, so filling it is fast; it grows to fit its content (the panel scrolls)."""

    TAGS = {"ok": OK, "warn": WARN, "err": ERR, "info": INFO, "accent": ACCENT, "teal": TEAL, "muted": MUTED,
            "faint": FAINT, "crit": CRIT}
    NAV = CopyableText.NAV

    def __init__(self, master):
        super().__init__(master, bd=0, highlightthickness=0, wrap="word", height=1, width=10, padx=0, pady=0,
                         cursor="arrow", takefocus=0, undo=False, exportselection=True)
        self.links, self.photos, self._n = {}, [], 0
        self.bind("<Key>", self._key)
        for ev in ("<<Paste>>", "<<Cut>>", "<<Clear>>"):
            self.bind(ev, lambda e: "break")
        self.bind("<Control-a>", lambda e: (self.tag_add("sel", "1.0", "end-1c"), "break")[1])
        self.bind("<Configure>", lambda e: self.after_idle(self.fit))
        # the wheel scrolls the panel around it; the text itself never scrolls (it shows everything)
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(ev, lambda e: self.after_idle(self._top), add="+")
        self.restyle()

    def _top(self):
        try:
            if self.yview()[0] > 0:
                self.yview_moveto(0)
                self.fit()
        except tk.TclError:
            pass

    def _key(self, e):
        if e.state & 0x4 and e.keysym.lower() in ("c", "insert", "a"):
            return None
        return None if e.keysym in self.NAV else "break"

    def restyle(self):
        self.configure(bg=pick(CARD), fg=pick(TEXT), font=tk_font(12), selectbackground=pick(SEL),
                       selectforeground=pick(TEXT), inactiveselectbackground=pick(SEL),
                       spacing1=px(1), spacing3=px(1))
        self.tag_configure("h", font=tk_font(13, "bold"), foreground=pick(TEXT), spacing1=px(14), spacing3=px(5))
        self.tag_configure("h2", font=tk_font(12, "bold"), foreground=pick(TEXT), spacing1=px(8), spacing3=px(2))
        self.tag_configure("bold", font=tk_font(12, "bold"))
        self.tag_configure("small", font=tk_font(11))
        self.tag_configure("mono", font=tk_font(11, family=MONO), foreground=pick(MUTED), lmargin1=px(2),
                           lmargin2=px(2))
        self.tag_configure("indent", lmargin1=px(16), lmargin2=px(16))
        self.tag_configure("bullet", lmargin1=px(2), lmargin2=px(18))
        for name, col in self.TAGS.items():
            self.tag_configure(name, foreground=pick(col))
        self.tag_configure("link", foreground=pick(ACCENT), font=tk_font(12, "bold"))
        self.tag_configure("chip", background=pick(ACCENT_SOFT), foreground=pick(ACCENT), font=tk_font(11, "bold"))
        for sev, col in SEV_COLOR.items():
            self.tag_configure("sev_" + sev, foreground=pick(col), font=tk_font(12, "bold"))
        self.tag_raise("link")

    # ---- writing
    def clear(self):
        self.delete("1.0", "end")
        for t in list(self.links):
            self.tag_delete(t)
        self.links.clear()
        self.photos.clear()

    def _nl(self):
        if self.index("end-1c") != "1.0":
            self.insert("end", "\n")

    def h(self, text, small=False):
        self._nl()
        self.insert("end", text, ("h2" if small else "h",))

    def p(self, text, *tags):
        self._nl()
        self.insert("end", text, tags)

    def bullet(self, text, *tags, mark="•"):
        self._nl()
        self.insert("end", f"{mark}  ", ("bullet",) + tags)
        self.insert("end", text, ("bullet",) + tags)

    def add(self, text, *tags):
        """Append on the current line."""
        self.insert("end", text, tags)

    def link(self, text, command, *tags):
        self._n += 1
        name = f"lnk{self._n}"
        self.insert("end", text, ("link", name) + tags)
        self.tag_bind(name, "<Button-1>", lambda e: command())
        self.tag_bind(name, "<Enter>", lambda e: self.configure(cursor="hand2"))
        self.tag_bind(name, "<Leave>", lambda e: self.configure(cursor="arrow"))
        self.links[name] = command

    def picture(self, pil_image, command=None, pad=3):
        """A small picture inline (pil_image already at real pixel size)."""
        if pil_image is None:
            return
        from PIL import ImageTk
        ph = ImageTk.PhotoImage(pil_image)
        self.photos.append(ph)
        idx = self.image_create("end", image=ph, padx=px(pad), pady=px(pad))
        if command:
            self._n += 1
            name = f"lnk{self._n}"
            self.tag_add(name, idx)
            self.tag_bind(name, "<Button-1>", lambda e: command())
            self.tag_bind(name, "<Enter>", lambda e: self.configure(cursor="hand2"))
            self.tag_bind(name, "<Leave>", lambda e: self.configure(cursor="arrow"))
            self.links[name] = command

    def fit(self):
        """Grow to show everything (the panel around it scrolls)."""
        try:
            n = self.count("1.0", "end", "update", "ypixels")
        except tk.TclError:
            return
        if isinstance(n, tuple):
            n = n[0] if n else 0
        n = int(n or 0)
        line = max(1, tk_font(12).metrics("linespace"))
        want = max(1, math.ceil(n / line) + 1)
        if int(self.cget("height")) != want:
            self.configure(height=want)


class DetailPane(ctk.CTkFrame):
    """The detail panel on the right of a list: a picture, a title, chips, a row of action buttons and
    formatted text, all kept and updated in place (fast) instead of rebuilt on every click.

    Usage: begin(); picture(); heading(); chips(); actions(); write to .text; end()."""

    def __init__(self, parent, n_actions=8):
        super().__init__(parent, fg_color=BG, corner_radius=0)
        self.body = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=12, border_width=1,
                                           border_color=BORDER)
        self.body.pack(fill="both", expand=True)
        self.body.grid_columnconfigure(0, weight=1)
        b = self.body
        self.stripe = ctk.CTkFrame(b, height=4, width=1, corner_radius=2, fg_color=ACCENT)
        self.pic = ctk.CTkLabel(b, text="")
        self.title = ctk.CTkLabel(b, text="", text_color=TEXT, font=font(16, "bold"), anchor="w", justify="left")
        self.sub = ctk.CTkLabel(b, text="", text_color=MUTED, font=font(11), anchor="w", justify="left")
        self.chip_row = ctk.CTkFrame(b, fg_color="transparent")
        self.chip_pool = []
        self.act_row = ctk.CTkFrame(b, fg_color="transparent")
        self.act_row.grid_columnconfigure((0, 1), weight=1, uniform="act")
        self.act_pool = [button(self.act_row, "", None, height=32, width=10) for _ in range(n_actions)]
        self.text = RichText(b)
        self.stripe.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        self.pic.grid(row=1, column=0, pady=(10, 2))
        self.title.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.sub.grid(row=3, column=0, sticky="ew", padx=16, pady=(1, 0))
        self.chip_row.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 0))
        self.act_row.grid(row=5, column=0, sticky="ew", padx=14, pady=(10, 2))
        self.text.grid(row=6, column=0, sticky="ew", padx=16, pady=(4, 16))
        self.on_resize = None
        self._pic_cmd = None
        self.pic.bind("<Button-1>", lambda e: self._pic_cmd() if self._pic_cmd else None)
        self._width, self._job, self._req = 0, None, None
        self._used = set()
        self._pics = {}
        self.bind("<Configure>", self._configured)

    # ---- size
    def _configured(self, e):
        if abs(e.width - self._width) < 8:
            return
        first = self._width == 0
        self._width = e.width
        if first or not self.on_resize:
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(160, self._resized)

    def _resized(self):
        self._job = None
        if self.on_resize:
            self.on_resize()

    def inner(self):
        """Usable width inside the panel, in design units."""
        w = self.body.winfo_width()
        if w < 50:
            w = self._width or self.winfo_width()
            w = (w if w > 50 else px(DETAIL_WIDTH)) - px(22)
        return max(180, units(w) - 32)

    def wrap(self):
        return self.inner()

    def side(self):
        """The square picture's side, in design units: the panel's width, but never more than about half
        its height, so the title and buttons stay in view on a short window."""
        s = min(360, self.inner())
        h = self.winfo_height()
        if h > 100:
            s = min(s, units(h) * 0.62)
        return int(max(150, s))

    # ---- filling it
    def request(self, fn, delay=40):
        """Run fn shortly (clicking through a list quickly only draws the last one)."""
        if self._req:
            self.after_cancel(self._req)
        self._req = self.after(delay, lambda: (setattr(self, "_req", None), fn()))

    def begin(self):
        self._used = set()
        self._pic_cmd = None
        self.text.clear()

    def picture(self, pil_image, key=None, command=None):
        """A square picture across the panel (pil_image: any size; drawn crisp at the display scale).
        command: what clicking it does (e.g. open it full size)."""
        if pil_image is None:
            return
        self._pic_cmd = command
        self.pic.configure(cursor="hand2" if command else "")
        s = self.side()
        k = (key, s) if key else None
        img = self._pics.get(k) if k else None
        if img is None:
            img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(s, s))
            if k:
                if len(self._pics) > 60:
                    self._pics.clear()
                self._pics[k] = img
        self.pic.configure(image=img)
        self._used.add("pic")

    def accent(self, color):
        self.stripe.configure(fg_color=color)
        self._used.add("stripe")

    def heading(self, title, sub="", sub_color=MUTED):
        w = self.wrap()
        self.title.configure(text=title, wraplength=w)
        self._used.add("title")
        if sub:
            self.sub.configure(text=sub, text_color=sub_color, wraplength=w)
            self._used.add("sub")

    def chips(self, items):
        """items: [(text, colour, soft colour, icon name or None, CTkImage or None)]"""
        for i, (text, col, soft, ic, img) in enumerate(items):
            if i >= len(self.chip_pool):
                self.chip_pool.append(ctk.CTkLabel(self.chip_row, text="", corner_radius=9, height=24,
                                                   font=font(11, "bold"), padx=8, compound="left"))
            c = self.chip_pool[i]
            c.configure(text=(" " + text) if (ic or img) else text, text_color=col, fg_color=soft,
                        image=img or (icon(ic, 13, col) if ic else None))
            c.pack_forget()
        for c in self.chip_pool[len(items):]:
            c.pack_forget()
        # flow: as many on a line as fit, the rest on the next line
        try:
            self.chip_row.update_idletasks()
        except Exception:
            pass
        avail = self.body.winfo_width() - px(44)
        if avail < px(120):
            avail = px(DETAIL_WIDTH - 44)
        lines = getattr(self, "_chip_lines", None)
        if lines is None:
            lines = self._chip_lines = []
        line, x = 0, 0
        for i in range(len(items)):
            c = self.chip_pool[i]
            w = c.winfo_reqwidth() + px(6)
            if x and x + w > avail:
                line, x = line + 1, 0
            while line >= len(lines):
                f = ctk.CTkFrame(self.chip_row, fg_color="transparent", height=1)
                lines.append(f)
            lines[line].grid(row=line, column=0, sticky="w", pady=(0, 4))
            c.pack(in_=lines[line], side="left", padx=(0, 6))
            c.tk.call("raise", c._w)                    # above the line frame it sits in
            x += w
        for f in lines[line + 1 if items else 0:]:
            f.grid_remove()
        if items:
            self._used.add("chips")

    def actions(self, items):
        """items: [(label, command, icon name, kind, enabled)] laid out two per row."""
        for i, it in enumerate(items[:len(self.act_pool)]):
            label, cmd, ic, kind = it[:4]
            enabled = it[4] if len(it) > 4 else True
            b = self.act_pool[i]
            style_button(b, (kind or "normal") if enabled else "normal", ic, 14)
            b.configure(text=label, command=cmd, state="normal" if enabled else "disabled")
            wide = len(items) % 2 == 1 and i == len(items) - 1
            b.grid(row=i // 2, column=(i % 2), columnspan=2 if wide else 1, sticky="ew",
                   padx=(0, 0 if wide or i % 2 else 6), pady=3)
        for b in self.act_pool[len(items):]:
            b.grid_remove()
        if items:
            self._used.add("actions")

    def end(self):
        for name, w in (("stripe", self.stripe), ("pic", self.pic), ("title", self.title), ("sub", self.sub),
                        ("chips", self.chip_row), ("actions", self.act_row)):
            if name in self._used:
                w.grid()
            else:
                w.grid_remove()
        self.text.fit()
        self.after_idle(self.text.fit)
        try:
            self.body._parent_canvas.yview_moveto(0)
        except Exception:
            pass

    def message(self, text, icon_name=None):
        """Nothing selected: a short hint."""
        self.begin()
        self.text.p(text, "muted")
        self.end()

    def restyle(self):
        self.text.restyle()

    def clear(self):
        self.begin()
        self.end()


# ------------------------------------------------------------------ right-click menus
_menu_icons = {}
RIGHT_CLICK = ("<Button-3>", "<Button-2>") if sys.platform == "darwin" else ("<Button-3>",)


def _menu_icon(name, color):
    key = (name, color, round(scale(), 2))
    if key not in _menu_icons:
        try:
            from PIL import ImageTk
            im = glyphs.draw(name, px(16), color)
            _menu_icons[key] = ImageTk.PhotoImage(im) if im is not None else None
        except Exception:
            _menu_icons[key] = None
    return _menu_icons[key]


def popup_menu(widget, event, items):
    """A right-click menu at the pointer. items: (label, icon name, command[, enabled]), None for a line,
    False for an entry left out; (label, icon, [sub items]) opens a sub-menu."""
    def build(parent, entries):
        m = tk.Menu(parent, tearoff=0, bg=pick(CARD), fg=pick(TEXT), activebackground=pick(SEL),
                    activeforeground=pick(TEXT), disabledforeground=pick(FAINT), bd=0, relief="flat",
                    font=tk_font(12), activeborderwidth=0)
        last_sep = True
        for it in entries:
            if it is False:
                continue
            if it is None:
                if not last_sep:
                    m.add_separator()
                    last_sep = True
                continue
            label, ic, cmd = it[0], it[1], it[2]
            enabled = it[3] if len(it) > 3 else True
            img = _menu_icon(ic, pick(ERR) if label.startswith("Delete") else pick(MUTED)) if ic else None
            opts = dict(label="  " + label, state="normal" if enabled else "disabled")
            if img is not None:
                opts.update(image=img, compound="left")
            if isinstance(cmd, list):
                m.add_cascade(menu=build(m, cmd), **opts)
            else:
                m.add_command(command=cmd, **opts)
            last_sep = False
        if last_sep and m.index("end") is not None:
            m.delete("end")
        return m
    menu = build(widget, items)
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def copy_text(widget, text):
    widget.clipboard_clear()
    widget.clipboard_append(text)


def error_log(app_dir, text):
    """Append an unexpected error to .work/errors.log (never raises)."""
    try:
        import time
        d = os.path.join(app_dir, ".work")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "errors.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + text.rstrip() + "\n\n")
    except Exception:
        pass
