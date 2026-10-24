"""
Adromedary's Paradoxical Launcher 1.0

A mod manager and launcher for Paradox games (Crusader Kings III, Europa Universalis IV/V, Stellaris,
Hearts of Iron IV, Victoria 3, Imperator):

Browse:    the game's Steam Workshop inside the app: search, sort, categories, version fit, pictures.
Catch:     downloads mods (or whole collections) through a chain of sites and installs them into the
           game's mod folder. Downloads pause and resume.
Library:   every installed mod with its role, conflicts, version notes and Workshop updates.
Playsets:  named mod lists in load order, Auto-sort, and Play to start the game with them directly.
Conflicts: everything that can go wrong in the active playset, explained.
Crashes:   after a crash: the mods most likely to blame, with the evidence, and a step-by-step culprit hunt.

Run:   python paradoxical_launcher.py
Build: double-click build.bat  (dist\\ParadoxicalLauncher.exe), or on Linux ./build_linux.sh  (dist/ParadoxicalLauncher)
"""
import hashlib
import json
import multiprocessing
import subprocess
import sys
import os
import pickle
import queue
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

import analysis as A
import appicon
import engine as E
import help_text as HT
import icons
import installer
import launcher as LA
import modscan
import sources as S
import storage as ST
import updates as U
import versions as V
from browser_helper import BrowserBridge
from gui_browse import BrowsePage
from gui_catch import KIND_COLOR, CatchPage
from gui_common import DATA_HINT, DATA_ROOT_HINT, IS_WIN
from gui_common import (COLORFUL, PALETTE, TAB_COLORS, Ribbon, ACCENT, ACCENT_HI, ACCENT_SOFT, APP_DIR, APP_NAME, APP_SHORT, APP_VERSION, AUTHOR, BG, BORDER,
                        CARD, CARD_HI, COLUMNS, CRIT, ERR, FAINT, MUTED, MUTED_SOFT, OK, PLAY, PLAY_HI, SHADOW,
                        SURFACE, TEAL, TEAL_SOFT, TEXT, THEMES, WARN, WARN_ICON, WARN_SOFT, WHITE,
                        Banner, button, card, ctk_image, error_log, fit_geometry, font, icon, open_folder, pick, px,
                        set_root, Split, style_trees, TabBar, Tooltip, units)
from gui_conflicts import ConflictsPage
from gui_crash import CrashPage
from gui_library import LibraryPage
from gui_playsets import PlaysetsPage
from profiles import Profiles

SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
REGISTRY_FILE = os.path.join(APP_DIR, "installed.json")
UPDATES_FILE = os.path.join(APP_DIR, "updates.json")
PROFILES_FILE = os.path.join(APP_DIR, "profiles.json")
CATCH_FILE = os.path.join(APP_DIR, "catch_list.json")     # Browse's catch list, kept until each mod is installed
WORK_DIR = os.path.join(APP_DIR, ".work")
TABS = ["Browse", "Catch", "Library", "Playsets", "Conflicts", "Crashes"]
TAB_ICONS = {"Browse": "browse", "Catch": "download", "Library": "library", "Playsets": "playsets",
             "Conflicts": "conflicts", "Crashes": "crash"}
OTHER_FOLDER = "Other mod folder..."

DEFAULTS = {
    "mod_dir": "",
    "other_dir": os.path.join(APP_DIR, "downloads"),
    "workers": 2,
    "order": list(S.DEFAULT_ORDER),
    "enabled": {k: True for k in S.DEFAULT_ORDER},
    "steam_owned": {},            # {game: True/False}: Steam only serves Workshop files to owners
    "steam_user": "", "modio_key": "", "github_token": "",
    "skip_existing": True,
    "check_window": True,
    "verify_timeout": 300,        # seconds to wait for you to tick a site's human check
    "steam_idle_timeout": 0,      # 0 = automatic (4 min anonymous, 15 min with a login)
    "mod_sort": "Name",
    "mod_sort_desc": False,
    "ignored_mods": {},           # {mod folder: [.mod file names]} whose conflicts aren't flagged
    "game_versions": {},          # {mod folder: "1.20"} the game version you play, for version warnings
    "game_dirs": {},              # {game: install folder}
    "theme": "System",
    "tab": "Browse",
    "show_log": True,
    "workshop_hints": True,       # read Workshop pages for "load after X" notes when sorting
    "older_first": False,         # Auto-sort: mods made for older game versions load first
    "palette": "Classic",         # Classic or Colorful (read at start: changing it takes a restart)
    "seen_version": "",           # the last version whose "What's new" was shown
    "add_new_to_playset": True,   # freshly downloaded mods join the active playset
    "play_continue": False,
    "play_debug": False,
    "ws_sort": "Trending this week",
    "ws_hide_installed": False,
    "ws_view": "List",
    "panes": {},                  # remembered sizes of the resizable panels
    "welcome_done": False,
    "geometry": "",
    "catch_links": "",            # the Catch tab's links box, kept between sessions
    "columns": {},                # list column widths you dragged
    "ask_deps": True,             # ask whether to catch the mods a mod needs
    "cleanup_limit_mb": 250,      # offer to clear cached pictures and pages above this size
    "role_overrides": {},         # {mod folder: {.mod file: role id}} roles you set yourself
    "lib_playset": "All mods",    # which playset the Library shows
    "hidden_issues": {},          # {mod folder: [conflict signatures]} conflicts you've hidden
    "seen_crashes": [],           # crash folders already opened in the Crashes tab
    "crash_hunt": {},             # a culprit hunt in progress (Crashes tab)
}
# Kept as they are when the Settings window saves (they're changed elsewhere in the app).
NOT_IN_SETTINGS_WINDOW = ("mod_dir", "workers", "game_versions", "ignored_mods", "tab", "show_log", "play_continue",
                          "play_debug", "mod_sort", "mod_sort_desc", "ws_sort", "ws_hide_installed", "ws_view",
                          "panes", "welcome_done", "geometry", "catch_links", "columns", "role_overrides",
                          "lib_playset", "hidden_issues", "seen_version", "seen_crashes", "crash_hunt")


def load_settings():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
        if saved and "welcome_done" not in saved:        # settings from an older version: not a first run
            cfg["welcome_done"] = True
    except Exception:
        pass
    order = [k for k in cfg["order"] if k in S.SOURCE_BY_KEY]
    cfg["order"] = order + [k for k in S.DEFAULT_ORDER if k not in order]
    cfg["enabled"] = {k: bool(cfg["enabled"].get(k, True)) for k in S.DEFAULT_ORDER}
    if not any(cfg["enabled"].values()):
        cfg["enabled"]["steam"] = True
    cfg["workers"] = max(1, min(5, int(cfg.get("workers") or 1)))
    if cfg.get("tab") not in TABS:
        cfg["tab"] = "Browse"
    if not cfg["mod_dir"]:
        found = installer.detect_mod_dirs()
        if found:
            cfg["mod_dir"] = found[0][1]          # Crusader Kings III first when present
    return cfg


def save_settings(cfg):
    try:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        pass


def load_catch_list():
    """{workshop id: title} in the order they were added."""
    try:
        with open(CATCH_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {str(x["id"]): str(x.get("title") or x["id"]) for x in data.get("items", []) if x.get("id")}
    except Exception:
        return {}


def save_catch_list(items):
    try:
        tmp = CATCH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"items": [{"id": k, "title": v} for k, v in items.items()]}, f, indent=1)
        os.replace(tmp, CATCH_FILE)
    except Exception:
        pass


def steam_allowed(cfg, game):
    """Is Steam part of the download chain for this game? (switched on, and the game is owned there)"""
    return bool(cfg["enabled"].get("steam", True)) and cfg.get("steam_owned", {}).get(game) is not False


# ================================================================== loading screen
class Splash(ctk.CTkToplevel):
    """Shown once while the app starts: builds every tab, reads the mods, loads (or works out) the
    analysis, decodes the pictures and draws the lists, so the window opens ready to use."""

    W, H, R = 480, 320, 22                    # design size and corner radius
    PAPER = ("#fbf8f1", "#1f1c25")            # a warm sheet of paper (light) / dark vellum
    EDGE = ("#d9ccb2", "#3b3446")

    def __init__(self, app):
        dark = ctk.get_appearance_mode() == "Dark"
        edge = self.EDGE[1 if dark else 0]
        # the corners outside the rounded sheet are made see-through (Windows): a colour one step off
        # the edge colour, so the smoothed corner pixels blend into the edge and leave no fringe
        key = "#%02x%02x%02x" % tuple(min(255, int(edge[i:i + 2], 16) + (1 if i == 1 else 0)) for i in (1, 3, 5))
        super().__init__(app, fg_color=key)
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        rounded = True
        try:
            self.attributes("-transparentcolor", key)
        except tk.TclError:                   # not on this system: a plain sheet with square corners
            rounded = False
            self.configure(fg_color=edge)
        sheet = ctk.CTkFrame(self, fg_color=self.PAPER, corner_radius=self.R if rounded else 0,
                             border_width=2, border_color=self.EDGE, bg_color=key if rounded else edge)
        sheet.pack(fill="both", expand=True)
        inner = ctk.CTkFrame(sheet, fg_color="transparent")          # centred on the sheet
        inner.pack(expand=True, padx=self.R // 2 + 4, pady=self.R // 2 + 2)
        try:
            self._logo = ctk_image(appicon.render(256), (104, 104))
            ctk.CTkLabel(inner, text="", image=self._logo).pack(pady=(0, 6))
        except Exception:
            pass
        ctk.CTkLabel(inner, text=APP_NAME, text_color=TEXT, font=font(18, "bold")).pack()
        ctk.CTkLabel(inner, text=f"version {APP_VERSION}  ·  by {AUTHOR}", text_color=MUTED,
                     font=font(11)).pack(pady=(2, 0))
        ctk.CTkFrame(inner, fg_color=self.EDGE, height=1, width=300).pack(pady=(14, 0))   # a ruled line
        self.bar = ctk.CTkProgressBar(inner, width=330, height=6, corner_radius=3, fg_color=self.EDGE,
                                      progress_color=ACCENT)
        self.bar.set(0)
        self.bar.pack(pady=(14, 6))
        self.lbl = ctk.CTkLabel(inner, text="Starting...", text_color=MUTED, font=font(11))
        self.lbl.pack()
        self.center()
        self.update()

    def center(self):
        """In the middle of the screen, measured from the size it really gets (the display scale applied:
        before it's drawn, Windows reports no size yet)."""
        try:
            k = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            k = 1.0
        w, h = round(self.W * k), round(self.H * k)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 2)
        tk.Toplevel.geometry(self, f"{w}x{h}+{x}+{y}")     # real pixels: no second scaling

    def step(self, text, fraction):
        try:
            self.lbl.configure(text=text)
            self.bar.set(max(0.0, min(1.0, fraction)))
            self.update()
        except tk.TclError:
            pass


# ================================================================== required mods
class DepsDialog(ctk.CTkToplevel):
    """A mod needs other Workshop mods you don't have (or have in an older version): catch them too?"""

    def __init__(self, app, ids, needed, on_choice):
        super().__init__(app, fg_color=BG)
        self.on_choice, self.done = on_choice, False
        titles = [app.catch_list.get(i) or app.browse_title(i) for i in ids]
        n = len(needed)
        self.title(f"Required mods - {APP_NAME}")
        fit_geometry(self, 580, 270 + 34 * min(n, 8), app)
        self.minsize(480, 300)
        self.transient(app)
        appicon.apply(self, APP_DIR)
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("cancel"))
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=22, pady=(6, 18))       # first: always in view
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(20, 8))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(body, text="", image=icon("chain", 30, ACCENT), width=48, height=48, corner_radius=24,
                     fg_color=ACCENT_SOFT).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
        who = f"\"{titles[0]}\"" if len(ids) == 1 and titles[0] else f"{len(ids)} mods you picked"
        ctk.CTkLabel(body, text=f"{who} need{'s' if len(ids) == 1 else ''} {n} other mod{'s' if n != 1 else ''}",
                     text_color=TEXT, font=font(16, "bold"), anchor="w", justify="left", wraplength=430
                     ).grid(row=0, column=1, sticky="ew")
        miss = sum(1 for x in needed if x[2] == "missing")
        upd = n - miss
        bits = ([f"{miss} you don't have"] if miss else []) + ([f"{upd} you have in an older version"] if upd else [])
        ctk.CTkLabel(body, text=" and ".join(bits).capitalize() + ". Without them, the mod may not work.",
                     text_color=MUTED, font=font(12), anchor="w", justify="left", wraplength=430
                     ).grid(row=1, column=1, sticky="ew", pady=(2, 0))
        box = ctk.CTkScrollableFrame(body, fg_color=CARD, corner_radius=10, border_width=1, border_color=BORDER,
                                     height=min(8, n) * 32 + 8)
        box.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        box.grid_columnconfigure(1, weight=1)
        by_id = dict(zip(ids, titles))
        for r, (rid, title, kind, by) in enumerate(needed):
            col, soft = (ACCENT, ACCENT_SOFT) if kind == "update" else (WARN, WARN_SOFT)
            ctk.CTkLabel(box, text="Update" if kind == "update" else "Missing", height=20, corner_radius=10,
                         fg_color=soft, text_color=col, font=font(10, "bold"), padx=7
                         ).grid(row=r, column=0, sticky="w", padx=(10, 8), pady=4)
            parent = by_id.get(by, "")
            ctk.CTkLabel(box, text=title + (f"   (for {parent})" if parent and len(ids) > 1 else ""),
                         text_color=TEXT, font=font(12), anchor="w").grid(row=r, column=1, sticky="ew", pady=4)
        button(foot, "Cancel", lambda: self._choose("cancel"), width=86, height=34).pack(side="left")
        button(foot, f"Catch with the {n} needed", lambda: self._choose("with"), primary=True, height=34,
               icon_name="download").pack(side="right")
        button(foot, "Only what I picked", lambda: self._choose("only"), height=34).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self._choose("cancel"))
        self.bind("<Return>", lambda e: self._choose("with"))
        self.after(120, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass

    def _choose(self, choice):
        if self.done:
            return
        self.done = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.on_choice(choice)


# ================================================================== first run
class WelcomeWindow(ctk.CTkToplevel):
    """Two questions before the app starts: which game, and is it owned on Steam."""

    def __init__(self, app, on_done):
        super().__init__(app, fg_color=BG)
        self.app, self.on_done = app, on_done
        self.title(f"Welcome - {APP_NAME}")
        fit_geometry(self, 640, 600, app)
        self.minsize(560, 520)
        if app.winfo_viewable():
            self.transient(app)
        self.resizable(True, True)
        appicon.apply(self, APP_DIR)
        self.protocol("WM_DELETE_WINDOW", self._finish)
        self.games = installer.detect_mod_dirs()
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=(22, 10))
        body.grid_columnconfigure(1, weight=1)
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        try:
            logo = ctk_image(appicon.render(128), (58, 58))
            ctk.CTkLabel(top, text="", image=logo).pack(side="left", padx=(0, 14))
        except Exception:
            pass
        tt = ctk.CTkFrame(top, fg_color="transparent")
        tt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(tt, text=f"Welcome to {APP_NAME}", text_color=TEXT, font=font(19, "bold"), anchor="w",
                     justify="left", wraplength=480).pack(fill="x")
        ctk.CTkLabel(tt, text="Find, download, sort and play mods for Paradox games. Two quick questions and "
                              "you're set; both can be changed later in Settings.", text_color=MUTED, font=font(12),
                     anchor="w", justify="left", wraplength=480).pack(fill="x", pady=(2, 0))

        # 1. the game
        self._step(body, 1, 1, "Which game do you play?")
        names = [g for g, _ in self.games] or ["(no Paradox game found)"]
        cur = app.game() or names[0]
        self.game = ctk.CTkOptionMenu(body, values=names, width=260, height=32, fg_color=CARD, button_color=CARD,
                                      button_hover_color=BORDER, text_color=TEXT, font=font(12, "bold"),
                                      dynamic_resizing=False, command=lambda v: self._game_changed())
        self.game.set(cur if cur in names else names[0])
        self.game.grid(row=2, column=1, sticky="w", padx=(0, 0), pady=(0, 2))
        self.where = ctk.CTkLabel(body, text="", text_color=MUTED, font=font(10), anchor="w", justify="left",
                                  wraplength=500)
        self.where.grid(row=3, column=1, sticky="ew")

        # 2. Steam
        self._step(body, 4, 2, "Do you own this game on Steam?")
        self.owned = ctk.StringVar(value="yes")
        opts = ctk.CTkFrame(body, fg_color="transparent")
        opts.grid(row=5, column=1, sticky="ew")
        self.r_yes = ctk.CTkRadioButton(opts, text="Yes, it's in my Steam library", variable=self.owned, value="yes",
                                        text_color=TEXT, font=font(12), fg_color=ACCENT, command=self._owned_changed)
        self.r_yes.pack(anchor="w", pady=3)
        ctk.CTkRadioButton(opts, text="No (GOG, Xbox / Game Pass, Paradox store or another shop)",
                           variable=self.owned, value="no", text_color=TEXT, font=font(12), fg_color=ACCENT,
                           command=self._owned_changed).pack(anchor="w", pady=3)
        self.hint = ctk.CTkLabel(body, text="", text_color=MUTED, font=font(11), anchor="w", justify="left",
                                 wraplength=500)
        self.hint.grid(row=6, column=1, sticky="ew", pady=(6, 0))
        self.acct = ctk.CTkFrame(body, fg_color="transparent")
        self.acct.grid(row=7, column=1, sticky="ew", pady=(10, 0))
        self.acct.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.acct, text="Your Steam account name (optional)", text_color=TEXT, font=font(12, "bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.user = ctk.StringVar(value=app.cfg.get("steam_user", ""))
        ctk.CTkEntry(self.acct, textvariable=self.user, width=260, height=30, fg_color=CARD, border_color=BORDER,
                     text_color=TEXT, placeholder_text="login name, not your e-mail").grid(row=1, column=0, sticky="w",
                                                                                          pady=(3, 2))
        ctk.CTkLabel(self.acct, text="Paradox games only give Workshop files to the account that owns them. The "
                                     "first time, SteamCMD (Valve's downloader) opens its own window for your password "
                                     "and Steam Guard code; the app never sees them. Without a name, Steam is tried "
                                     "anonymously and the other sites take over.",
                     text_color=MUTED, font=font(10), anchor="w", justify="left", wraplength=500
                     ).grid(row=2, column=0, sticky="ew")
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=26, pady=(0, 20))
        button(foot, "Start", self._finish, primary=True, width=140, height=38, icon_name="right").pack(side="right")
        self._game_changed()
        self.after(150, self._grab)

    def _step(self, parent, row, n, text):
        ctk.CTkLabel(parent, text=str(n), width=30, height=30, corner_radius=15, fg_color=ACCENT, text_color="white",
                     font=font(13, "bold")).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(22, 6))
        ctk.CTkLabel(parent, text=text, text_color=TEXT, font=font(15, "bold"), anchor="w"
                     ).grid(row=row, column=1, sticky="w", pady=(22, 6))

    def _grab(self):
        try:
            self.grab_set()
            self.focus()
        except Exception:
            pass

    def _game_changed(self):
        g = self.game.get()
        path = dict(self.games).get(g, "")
        self.where.configure(text=f"Mods go to {path}" if path else
                             f"No Paradox game was found in {DATA_ROOT_HINT}. Pick a mod folder "
                             "later with Game > Other mod folder.")
        known = self.app.cfg.get("steam_owned", {}).get(g)
        on_steam = LA.on_steam(g)
        self.owned.set("no" if known is False else "yes" if (known or on_steam) else "yes")
        self.found_on_steam = on_steam
        self._owned_changed()

    def _owned_changed(self):
        g = self.game.get()
        if self.owned.get() == "yes":
            self.hint.configure(text=(f"{g} was found in your Steam library. " if self.found_on_steam else "")
                                + "Steam is tried first for every mod; if it can't deliver one, the other sites "
                                  "take over.", text_color=MUTED)
            self.acct.grid()
        else:
            self.hint.configure(text="Steam only hands out Workshop mods to accounts that own the game, so Steam is "
                                     f"switched off for {g}. Mods come from the other sites (SkyMods, mod.io and "
                                     "more), which mirror most of the Workshop.", text_color=WARN)
            self.acct.grid_remove()

    def _finish(self):
        cfg = self.app.cfg
        g = self.game.get()
        path = dict(self.games).get(g, "")
        if path:
            cfg["mod_dir"] = path
            cfg.setdefault("steam_owned", {})[g] = self.owned.get() == "yes"
        if self.owned.get() == "yes":
            cfg["steam_user"] = self.user.get().strip()
        cfg["welcome_done"] = True
        self.app.save()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self.on_done()


# ================================================================== settings window
PROJECT_URL = "https://github.com/Adromedary/Adromedary-s-Paradoxical-Launcher"
# swatches for the palette cards in Settings > Appearance (fixed: the running palette may be the other one)
PALETTE_PREVIEW = [
    ("Classic", "Cool greys and blue: calm and plain.",
     ["#eceff5", "#ffffff", "#2563d9", "#13865a", "#b26a00", "#161b24"]),
    ("Colorful", "Warm parchment and royal tones. Every tab has its own colour, with a heraldic ribbon under "
                 "the top bar.", ["#ece2cf", "#fffaf1", "#7333a8", "#2458c9", "#1c8049", "#ad5f08", "#b8263a",
                                  "#1e1727"]),
]


class _Nav:
    """The Settings sidebar: get() / set(name) like a tab view (older names still work)."""
    ALIASES = {"Downloads": "General", "Auto-sort": "Sorting"}

    def __init__(self, win):
        self.win = win

    def get(self):
        return self.win.current

    def set(self, name):
        self.win.show_section(self.ALIASES.get(name, name))


class SettingsWindow(ctk.CTkToplevel):
    SECTIONS = [("General", "settings"), ("Games", "play"), ("Sorting", "sparkle"), ("Download sites", "download"),
                ("Accounts", "key"), ("Storage", "broom"), ("Appearance", "palette"), ("About", "crest")]

    def __init__(self, app, tab=None):
        super().__init__(app, fg_color=BG)
        self.app = app
        self.title(f"Settings - {APP_NAME}")
        fit_geometry(self, 940, 700, app)
        self.minsize(760, 540)
        self.transient(app)
        appicon.apply(self, APP_DIR)
        self.cfg = json.loads(json.dumps(app.cfg))
        self.game = app.game()
        self.switch_vars = {}
        self.current = None
        self.tabs = _Nav(self)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        nav = ctk.CTkFrame(self, fg_color=CARD_HI, corner_radius=0, width=214)
        nav.grid(row=0, column=0, rowspan=2, sticky="ns")
        nav.grid_propagate(False)
        ctk.CTkLabel(nav, text="  Settings", text_color=TEXT, font=font(18, "bold"), anchor="w",
                     image=icon("settings", 20), compound="left").pack(fill="x", padx=16, pady=(16, 12))
        self.navbtn = {}
        for name, ic in self.SECTIONS:
            b = ctk.CTkButton(nav, text="  " + name, anchor="w", height=34, corner_radius=8, font=font(12),
                              fg_color="transparent", hover_color=BORDER, text_color=TEXT, image=icon(ic, 16),
                              compound="left", command=lambda n=name: self.show_section(n))
            b.pack(fill="x", padx=8, pady=1)
            self.navbtn[name] = b
        ctk.CTkLabel(nav, text=f"{APP_SHORT} {APP_VERSION}", text_color=MUTED, font=font(10), anchor="w"
                     ).pack(side="bottom", fill="x", padx=16, pady=12)
        self.stack = ctk.CTkFrame(self, fg_color="transparent")
        self.stack.grid(row=0, column=1, sticky="nsew", padx=(14, 14), pady=(10, 0))
        self.stack.grid_columnconfigure(0, weight=1)
        self.stack.grid_rowconfigure(0, weight=1)
        self.pages = {}

        # ---- general
        g0 = self._section("General", "How downloads and new mods are handled.")
        d = self._group(g0, "Downloads")
        self.other_dir = self._field(d, 1, "Other games' mods", self.cfg["other_dir"],
                                     "Mods for a different game than the chosen one are saved here.", browse=True)
        self.skip = ctk.BooleanVar(value=self.cfg["skip_existing"])
        self._switch(d, 2, "Skip mods that are already installed (also copies Steam installed for you)", self.skip)
        self.add_new = ctk.BooleanVar(value=self.cfg.get("add_new_to_playset", True))
        self._switch(d, 3, "Add newly downloaded mods to the active playset", self.add_new)
        self.ask_deps = ctk.BooleanVar(value=self.cfg.get("ask_deps", True))
        self._switch(d, 4, "When a mod needs other Workshop mods I don't have, ask whether to catch them too",
                     self.ask_deps)
        has_view = BrowserBridge.available()
        self.check = ctk.BooleanVar(value=self.cfg["check_window"] and has_view)
        self._switch(d, 5, "When a site shows a 'verify you are human' check, open it in a window so I can tick it",
                     self.check, enabled=has_view)
        self._note(d, 6, "You tick the box yourself; the app never does it for you. Without this, a site showing "
                         "the check is skipped for that run." if has_view else
                         "Unavailable: the pywebview package is missing. Rebuild with " +
                         ("build.bat." if IS_WIN else "build_linux.sh."), indent=58)

        # ---- games
        gs = self._section("Games", "For each game: where it's installed (Play starts it from there, and the "
                                    "conflict check compares mods with the game's own files) and whether you own it "
                                    "on Steam (Steam only gives Workshop files to owners).")
        self.game_vars, self.owned_vars = {}, {}
        games = [n for n, _ in installer.detect_mod_dirs()]
        if app.game() and app.game() not in games:
            games.append(app.game())
        for game in dict.fromkeys(games + list(self.cfg.get("game_dirs", {}))):
            if not game:
                continue
            box = self._group(gs, game)
            cur = self.cfg.get("game_dirs", {}).get(game, "") or app.found_install(game)
            self.game_vars[game] = self._field(box, 1, "Install folder", cur, "", browse=True, find=game)
            var = ctk.BooleanVar(value=self.cfg.get("steam_owned", {}).get(game) is not False)
            self.owned_vars[game] = var
            ctk.CTkSwitch(box, text="I own it on Steam", variable=var, progress_color=ACCENT, text_color=TEXT,
                          font=font(12), command=self._draw_chain).grid(row=2, column=0, sticky="w", padx=12,
                                                                         pady=(2, 10))

        # ---- sorting and conflicts
        so = self._section("Sorting", "How Auto-sort decides, and the conflicts you've hidden.")
        a = self._group(so, "Auto-sort")
        self.hints = ctk.BooleanVar(value=self.cfg.get("workshop_hints", True))
        self._switch(a, 1, "Read the mods' Workshop pages for notes like \"load after X\"", self.hints)
        self.older = ctk.BooleanVar(value=self.cfg.get("older_first", False))
        self._switch(a, 2, "Mods made for older game versions load first (so newer ones win the files they share)",
                     self.older)
        self._note(a, 3, "Off by default: a mod made for an older version isn't always worse. Your own rules always "
                         "come first.", indent=58)
        c = self._group(so, "Conflicts")
        n_hidden = sum(len(v) for v in self.cfg.get("hidden_issues", {}).values())
        self.hidden_lbl = ctk.CTkLabel(c, text=f"{n_hidden} conflict{'s' if n_hidden != 1 else ''} hidden",
                                       text_color=TEXT, font=font(12), anchor="w")
        self.hidden_lbl.grid(row=1, column=0, sticky="w", padx=12, pady=(2, 4))
        self.unhide_btn = button(c, "Show them all again", self._unhide_all, icon_name="undo", width=170,
                                 state="normal" if n_hidden else "disabled")
        self.unhide_btn.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 12))

        # ---- download sites
        t = self._section("Download sites", "Each mod tries these sites from top to bottom until one delivers "
                                            "it. Switch sites off to shorten the chain; at least one stays on.")
        self.chain_box = ctk.CTkFrame(t, fg_color="transparent")
        self.chain_box.grid(row=2, column=0, sticky="ew")
        self.chain_box.grid_columnconfigure(0, weight=1)
        self.warn = ctk.CTkLabel(t, text="", text_color=WARN, font=font(12, "bold"), anchor="w")
        self.warn.grid(row=3, column=0, sticky="ew", padx=8)
        button(t, "Reset to default order", self._reset, width=170, icon_name="undo").grid(
            row=4, column=0, sticky="w", padx=4, pady=8)

        # ---- accounts
        ac = self._section("Accounts", "All optional. Without them those steps run anonymously or are skipped.")
        acc = self._group(ac, "Sign-ins and keys")
        self.steam_user = self._field(acc, 1, "Steam account name", self.cfg["steam_user"],
                                      "Your login name (not your e-mail), for games you own on Steam. SteamCMD asks "
                                      "for the password in its own window.")
        self.modio_key = self._field(acc, 2, "mod.io API key", self.cfg["modio_key"],
                                     "Free: mod.io > your account > API access. mod.io is skipped without it.",
                                     secret=True)
        self.github_token = self._field(acc, 3, "GitHub token", self.cfg["github_token"],
                                        "Optional. Raises GitHub's search limit from 10 to 30 a minute.", secret=True)

        # ---- storage
        st = self._section("Storage", "The app keeps pictures, screenshots and Workshop pages so they show up fast. "
                                      "They come back by themselves when needed, so clearing them loses nothing. "
                                      "Your mods, playsets, unfinished downloads, backups and the saved mod check "
                                      "are never touched.")
        lim = self._group(st, "Offer to clear them above")
        cur_mb = int(self.cfg.get("cleanup_limit_mb", ST.DEFAULT_LIMIT_MB))
        steps = ST.LIMITS_MB
        idx = min(range(len(steps)), key=lambda i: abs(steps[i] - cur_mb))
        row = ctk.CTkFrame(lim, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=12)
        row.grid_columnconfigure(1, weight=1)
        self.limit_lbl = ctk.CTkLabel(row, text=ST.label_mb(steps[idx]), text_color=ACCENT, font=font(14, "bold"),
                                      width=80, anchor="w")
        self.limit_lbl.grid(row=0, column=0, sticky="w")
        self.limit = ctk.CTkSlider(row, from_=0, to=len(steps) - 1, number_of_steps=len(steps) - 1,
                                   button_color=ACCENT, button_hover_color=ACCENT_HI, progress_color=ACCENT,
                                   command=lambda v: self.limit_lbl.configure(text=ST.label_mb(steps[int(round(v))])))
        self.limit.set(idx)
        self.limit.grid(row=0, column=1, sticky="ew")
        self._note(lim, 2, "100 MB to 10 GB. Checked each time the app starts.")
        now = self._group(st, "Right now")
        now.grid_columnconfigure(1, weight=0)
        self.usage = ctk.CTkLabel(now, text="Measuring...", text_color=TEXT, font=font(12), anchor="w",
                                  justify="left")
        self.usage.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.clear_btn = button(now, "Clear now", self._clear_storage, icon_name="broom", height=32,
                                state="disabled")
        self.clear_btn.grid(row=1, column=1, padx=12, pady=(0, 12))
        self._cats = []
        app.check_storage(on_done=self._measured)

        # ---- appearance
        ap = self._section("Appearance", "Pick a palette, and light or dark.")
        pg = self._group(ap, "Palette")
        cards = ctk.CTkFrame(pg, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 4))
        self.palette = self.cfg.get("palette", "Classic")
        self.pal_cards = {}
        for i, (name, blurb, sw) in enumerate(PALETTE_PREVIEW):
            card_ = ctk.CTkFrame(cards, fg_color=CARD, corner_radius=12, border_width=2, border_color=BORDER,
                                 cursor="hand2")
            card_.grid(row=0, column=i, padx=4, pady=4, sticky="n")
            strip = ctk.CTkFrame(card_, fg_color="transparent")
            strip.pack(anchor="w", padx=12, pady=(12, 6))
            for col in sw:
                ctk.CTkFrame(strip, width=26, height=26, corner_radius=6, fg_color=col, border_width=1,
                             border_color=BORDER).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(card_, text=name, text_color=TEXT, font=font(13, "bold"), anchor="w").pack(anchor="w", padx=12)
            ctk.CTkLabel(card_, text=blurb, text_color=MUTED, font=font(11), anchor="w", justify="left",
                         wraplength=250).pack(anchor="w", padx=12, pady=(0, 12))
            for w in [card_, strip] + list(card_.winfo_children()) + list(strip.winfo_children()):
                w.bind("<Button-1>", lambda e, n=name: self._pick_palette(n), add="+")
            self.pal_cards[name] = card_
        self.pal_note = ctk.CTkLabel(pg, text="", text_color=WARN, font=font(11, "bold"), anchor="w")
        self.pal_note.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 10))
        self._pick_palette(self.palette)
        mg = self._group(ap, "Light or dark")
        self.theme = ctk.CTkSegmentedButton(mg, values=THEMES, font=font(12), selected_color=ACCENT,
                                            selected_hover_color=ACCENT_HI, unselected_color=CARD_HI,
                                            unselected_hover_color=BORDER, text_color=TEXT, fg_color=BORDER)
        self.theme.set(self.cfg.get("theme", "System"))
        self.theme.grid(row=1, column=0, sticky="w", padx=12)
        self._note(mg, 2, "System follows your system's light/dark setting. The moon button in the top bar "
                          "switches too, with either palette.")
        lg = self._group(ap, "Layout")
        button(lg, "Reset panel sizes", self._reset_panes, width=150, icon_name="grid").grid(
            row=1, column=0, sticky="w", padx=12)
        self._note(lg, 2, "The dividers between lists and their detail panels can be dragged; this puts them back.")

        # ---- about
        ab = self._section("About", "")
        box = self._group(ab, APP_NAME)
        ctk.CTkLabel(box, text=f"Version {APP_VERSION}  ·  by {AUTHOR}", text_color=MUTED, font=font(12),
                     anchor="w").grid(row=1, column=0, sticky="w", padx=12)
        ctk.CTkLabel(box, text="Find, download and sort mods for Paradox games, see how they conflict, and play.",
                     text_color=TEXT, font=font(12), anchor="w", justify="left", wraplength=560
                     ).grid(row=2, column=0, sticky="w", padx=12, pady=(6, 8))
        brow = ctk.CTkFrame(box, fg_color="transparent")
        brow.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 12))
        button(brow, "What's new", lambda: WhatsNewWindow(app), icon_name="star", width=170).pack(side="left")
        button(brow, "Help", app._open_help, icon_name="help", width=90).pack(side="left", padx=8)
        button(brow, "Open the app folder", lambda: open_folder(APP_DIR), icon_name="folder", width=170
               ).pack(side="left")
        button(brow, "Project page", lambda: webbrowser.open(PROJECT_URL), icon_name="external", width=140
               ).pack(side="left", padx=8)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=1, column=1, sticky="ew", padx=14, pady=10)
        button(foot, "Save", self._save, primary=True, width=110, height=34, icon_name="check").pack(side="right")
        button(foot, "Cancel", self.destroy, width=90, height=34).pack(side="right", padx=8)
        self._draw_chain()
        self.show_section(_Nav.ALIASES.get(tab, tab) if tab else "General")
        self.after(150, self._grab)

    # ---- layout helpers
    def _section(self, name, sub):
        page = ctk.CTkScrollableFrame(self.stack, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(page, text=name, text_color=TEXT, font=font(20, "bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=4, pady=(6, 0))
        if sub:
            ctk.CTkLabel(page, text=sub, text_color=MUTED, font=font(12), anchor="w", justify="left",
                         wraplength=620).grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 8))
        page._next = 2
        self.pages[name] = page
        return page

    def _group(self, page, title):
        box = ctk.CTkFrame(page, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        box.grid(row=page._next + 10, column=0, sticky="ew", padx=2, pady=5)
        page._next += 1
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=title, text_color=TEXT, font=font(13, "bold"), anchor="w"
                     ).grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 4))
        return box

    def _note(self, parent, row, text, indent=12):
        ctk.CTkLabel(parent, text=text, text_color=MUTED, font=font(10), anchor="w", justify="left",
                     wraplength=560).grid(row=row, column=0, sticky="w", padx=(indent, 12), pady=(0, 10))

    def show_section(self, name):
        if name not in self.pages:
            return
        self.current = name
        page = self.pages[name]
        getattr(page, "_parent_frame", page).tkraise()       # a scrollable frame lives inside an outer frame
        for n, b in self.navbtn.items():
            b.configure(fg_color=ACCENT_SOFT if n == name else "transparent",
                        text_color=ACCENT if n == name else TEXT, font=font(12, "bold" if n == name else "normal"))

    def _pick_palette(self, name):
        self.palette = name
        for n, c in self.pal_cards.items():
            c.configure(border_color=ACCENT if n == name else BORDER)
        self.pal_note.configure(text="" if name == PALETTE else "Takes effect when the app restarts (it offers to "
                                                                 "restart when you save).")

    def _unhide_all(self):
        self.app.cfg["hidden_issues"] = {}
        self.cfg["hidden_issues"] = {}
        self.app.save()
        self.app.conflicts.render()
        self.app._tab_info()
        self.hidden_lbl.configure(text="0 conflicts hidden")
        self.unhide_btn.configure(state="disabled")

    def _measured(self, cats):
        if not self.winfo_exists():
            return
        self._cats = cats
        if not cats:
            self.usage.configure(text="Nothing cached right now.")
            self.clear_btn.configure(state="disabled")
            return
        lines = [f"{ST.human(ST.total(cats))} in cached files"] + [f"   {what}: {ST.human(n)}" for _, what, _, n in cats]
        self.usage.configure(text="\n".join(lines))
        self.clear_btn.configure(state="normal")

    def _clear_storage(self):
        if self._cats:
            self.clear_btn.configure(state="disabled")
            self.usage.configure(text="Clearing...")
            self.app.clear_storage(self._cats, on_done=lambda freed: self.app.check_storage(on_done=self._measured))

    def _grab(self):
        try:
            self.grab_set()
            self.focus()
        except Exception:
            pass

    def _switch(self, parent, row, text, var, enabled=True):
        ctk.CTkSwitch(parent, text=text, variable=var, progress_color=ACCENT, text_color=TEXT if enabled else MUTED,
                      font=font(12), state="normal" if enabled else "disabled"
                      ).grid(row=row, column=0, sticky="w", padx=12, pady=5)

    def _field(self, parent, row, label, value, hint, secret=False, browse=False, find=None):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=0, sticky="ew", padx=12, pady=5)
        box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(box, text=label, text_color=TEXT, font=font(12), width=150, anchor="w", justify="left",
                     wraplength=145).grid(row=0, column=0, sticky="w")
        var = ctk.StringVar(value=value)
        ctk.CTkEntry(box, textvariable=var, fg_color=BG, border_color=BORDER, text_color=TEXT, height=30,
                     show="*" if secret else "").grid(row=0, column=1, sticky="ew")
        if browse:
            button(box, "", lambda: self._browse_into(var), width=32, icon_name="folder").grid(row=0, column=2, padx=(6, 0))
        if find:
            button(box, "Find", lambda: self._find(find, var), width=56, icon_name="search").grid(row=0, column=3, padx=(6, 0))
        if hint:
            ctk.CTkLabel(box, text=hint, text_color=MUTED, font=font(10), anchor="w", justify="left",
                         wraplength=480).grid(row=1, column=1, sticky="w")
        return var

    def _browse_into(self, var):
        d = filedialog.askdirectory(parent=self, initialdir=var.get() or APP_DIR)
        if d:
            var.set(os.path.normpath(d))

    def _find(self, game, var):
        found = LA.find_installs(game)
        if found:
            var.set(found[0])
        else:
            messagebox.showinfo(APP_NAME, f"{game} wasn't found in Steam's or GOG's records. Use the folder button "
                                          "to pick its install folder.", parent=self)

    def _steam_on(self):
        """The Steam row's switch: on for the current game when it's switched on and owned there."""
        owned = self.owned_vars.get(self.game)
        own = owned.get() if owned is not None else self.cfg.get("steam_owned", {}).get(self.game) is not False
        return self.cfg["enabled"].get("steam", True) and own

    def _effective(self, key):
        return self._steam_on() if key == "steam" else self.cfg["enabled"][key]

    def _draw_chain(self):
        for w in self.chain_box.winfo_children():
            w.destroy()
        n_on = sum(1 for k in self.cfg["order"] if self._effective(k))
        pos = 0
        for i, key in enumerate(self.cfg["order"]):
            src = S.SOURCE_BY_KEY[key]
            on = self._effective(key)
            if on:
                pos += 1
            row = ctk.CTkFrame(self.chain_box, fg_color=CARD_HI if on else BG, corner_radius=10,
                               border_width=1, border_color=BORDER)
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=3)
            row.grid_columnconfigure(2, weight=1)
            ctk.CTkLabel(row, text=str(pos) if on else "-", width=26, text_color=TEXT if on else MUTED,
                         font=font(14, "bold")).grid(row=0, column=0, rowspan=2, padx=(8, 2))
            var = ctk.BooleanVar(value=on)
            self.switch_vars[key] = var
            ctk.CTkSwitch(row, text="", width=46, variable=var, progress_color=ACCENT,
                          command=lambda k=key, v=var: self._toggle(k, v)).grid(row=0, column=1, rowspan=2, padx=(4, 6))
            head = ctk.CTkFrame(row, fg_color="transparent")
            head.grid(row=0, column=2, sticky="ew", pady=(8, 0))
            ctk.CTkLabel(head, text=src.name, text_color=TEXT if on else MUTED, font=font(13, "bold")).pack(side="left")
            ctk.CTkLabel(head, text=src.kind, height=18, corner_radius=9, fg_color=BG if on else CARD,
                         text_color=KIND_COLOR.get(src.kind, MUTED), font=font(9, "bold")).pack(side="left", padx=8, ipadx=4)
            if src.needs and on and not self.cfg.get(src.needs):
                ctk.CTkLabel(head, text="needs a key (Accounts)", text_color=WARN, font=font(10)).pack(side="left")
            blurb = src.blurb
            if key == "steam" and self.game:
                blurb += (f"  On for {self.game}: you own it on Steam." if on else
                          f"  Off for {self.game}: you said you don't own it on Steam (Games)."
                          if self.cfg["enabled"].get("steam", True) else "")
            ctk.CTkLabel(row, text=blurb, text_color=MUTED, font=font(11), anchor="w", justify="left",
                         wraplength=470).grid(row=1, column=2, sticky="ew", pady=(0, 8))
            arrows = ctk.CTkFrame(row, fg_color="transparent")
            arrows.grid(row=0, column=3, rowspan=2, padx=8)
            button(arrows, "", lambda j=i: self._move(j, -1), width=30, height=24, icon_name="up", icon_size=13,
                   state="normal" if i > 0 else "disabled").pack(pady=1)
            button(arrows, "", lambda j=i: self._move(j, 1), width=30, height=24, icon_name="down", icon_size=13,
                   state="normal" if i < len(self.cfg["order"]) - 1 else "disabled").pack(pady=1)
        self.warn.configure(text="Only one site is on, so it can't be switched off." if n_on == 1 else "")

    def _toggle(self, key, var):
        on_now = sum(1 for k in self.cfg["order"] if self._effective(k))
        if not var.get() and on_now <= 1:
            var.set(True)
            self.warn.configure(text="At least one site has to stay on.")
            self.bell()
            return
        if key == "steam" and self.game:
            if var.get():
                self.cfg["enabled"]["steam"] = True
            if self.game in self.owned_vars:
                self.owned_vars[self.game].set(bool(var.get()))
            self.cfg.setdefault("steam_owned", {})[self.game] = bool(var.get())
        else:
            self.cfg["enabled"][key] = bool(var.get())
        self._draw_chain()

    def _move(self, i, d):
        o = self.cfg["order"]
        j = i + d
        if 0 <= j < len(o):
            o[i], o[j] = o[j], o[i]
            self._draw_chain()

    def _reset(self):
        self.cfg["order"] = list(S.DEFAULT_ORDER)
        self._draw_chain()

    def _reset_panes(self):
        self.app.cfg["panes"] = {}
        self.app.save()
        messagebox.showinfo(APP_NAME, "Panel sizes are reset. They're used the next time the app starts.", parent=self)

    def _save(self):
        dirs = {}
        for game, var in self.game_vars.items():
            v = var.get().strip()
            if v and not LA.looks_like_install(game, v):
                messagebox.showwarning(APP_NAME, f"{v}\ndoesn't look like a {game} install (no launcher settings "
                                                 "or game program found there).", parent=self)
                return
            if v:
                dirs[game] = os.path.normpath(v)
        owned = dict(self.cfg.get("steam_owned", {}))
        for game, var in self.owned_vars.items():
            owned[game] = bool(var.get())
        if not any(steam_allowed(dict(self.cfg, steam_owned=owned), self.game) if k == "steam" else
                   self.cfg["enabled"][k] for k in self.cfg["order"]):
            messagebox.showwarning(APP_NAME, "Every download site is off for this game. Switch at least one on.",
                                   parent=self)
            return
        self.cfg.update(steam_user=self.steam_user.get().strip(), modio_key=self.modio_key.get().strip(),
                        github_token=self.github_token.get().strip(), skip_existing=bool(self.skip.get()),
                        check_window=bool(self.check.get()), theme=self.theme.get(), palette=self.palette,
                        other_dir=self.other_dir.get().strip() or DEFAULTS["other_dir"],
                        add_new_to_playset=bool(self.add_new.get()), workshop_hints=bool(self.hints.get()),
                        older_first=bool(self.older.get()), game_dirs=dirs, steam_owned=owned, ask_deps=bool(self.ask_deps.get()),
                        cleanup_limit_mb=ST.LIMITS_MB[int(round(self.limit.get()))])
        self.app.apply_settings(self.cfg)
        self.destroy()
        if self.palette != PALETTE:
            self.app.after(100, self.app.offer_restart)


# ================================================================== what's new
class WhatsNewWindow(ctk.CTkToplevel):
    """What changed in this version, shown once after updating (and from Settings > About)."""

    def __init__(self, app):
        super().__init__(app, fg_color=BG)
        self.app = app
        self.title(f"What's new - {APP_NAME}")
        fit_geometry(self, 760, 680, app)
        self.minsize(560, 420)
        self.transient(app)
        appicon.apply(self, APP_DIR)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        head.grid(row=0, column=0, sticky="ew")
        try:
            self._logo = ctk_image(appicon.render(96), (44, 44))
            ctk.CTkLabel(head, text="", image=self._logo).pack(side="left", padx=(20, 12), pady=14)
        except Exception:
            pass
        txt = ctk.CTkFrame(head, fg_color="transparent")
        txt.pack(side="left", pady=14)
        ctk.CTkLabel(txt, text=f"What's new in {APP_VERSION}", text_color=TEXT, font=font(22, "bold"), anchor="w"
                     ).pack(anchor="w")
        ctk.CTkLabel(txt, text=HT.WHATS_NEW_INTRO, text_color=MUTED, font=font(12), anchor="w", justify="left",
                     wraplength=560).pack(anchor="w")
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(10, 0))
        body.grid_columnconfigure(0, weight=1)
        for r, (title, ic, lines) in enumerate(HT.WHATS_NEW):
            strong = TAB_COLORS[title][0] if (COLORFUL and title in TAB_COLORS) else ACCENT
            c = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
            c.grid(row=r, column=0, sticky="ew", padx=4, pady=5)
            c.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(c, text="  " + title, image=icon(ic, 18, strong), compound="left", text_color=TEXT,
                         font=font(14, "bold"), anchor="w").grid(row=0, column=0, columnspan=2, sticky="w",
                                                                 padx=12, pady=(10, 4))
            for n, line in enumerate(lines, 1):
                ctk.CTkLabel(c, text="•", text_color=strong, font=font(15, "bold"), width=18, height=20, anchor="n"
                             ).grid(row=n, column=0, sticky="n", padx=(16, 4), pady=1)
                ctk.CTkLabel(c, text=line, text_color=TEXT, font=font(12), anchor="w", justify="left",
                             wraplength=600).grid(row=n, column=1, sticky="w", padx=(0, 12),
                                                  pady=(1, 10 if n == len(lines) else 1))
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=16, pady=10)
        button(foot, "Close", self.destroy, primary=True, width=100, height=34).pack(side="right")
        button(foot, "Open Help", lambda: (self.destroy(), app._open_help()), icon_name="help", width=120,
               height=34).pack(side="right", padx=8)
        if not COLORFUL:
            button(foot, "Try the Colorful palette", self._try_colorful, icon_name="palette", width=200,
                   height=34).pack(side="left")
        self.after(100, self.lift)

    def _try_colorful(self):
        self.destroy()
        self.app._open_settings("Appearance")


# ================================================================== help window
class HelpWindow(ctk.CTkToplevel):
    """Topics on the left, one topic shown at a time on the right."""

    def __init__(self, app, topic=None):
        super().__init__(app, fg_color=BG)
        self.title(f"Help - {APP_NAME}")
        fit_geometry(self, 940, 720, app)
        self.minsize(720, 480)
        self.transient(app)
        appicon.apply(self, APP_DIR)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        nav = ctk.CTkFrame(self, fg_color=CARD_HI, corner_radius=0, width=220)
        nav.grid(row=0, column=0, rowspan=2, sticky="ns")
        nav.grid_propagate(False)
        ctk.CTkLabel(nav, text="  Help", text_color=TEXT, font=font(18, "bold"), anchor="w", image=icon("help", 20),
                     compound="left").pack(fill="x", padx=16, pady=(16, 0))
        ctk.CTkLabel(nav, text=f"{APP_SHORT} {APP_VERSION}\nby {AUTHOR}", text_color=MUTED, font=font(11), anchor="w",
                     justify="left").pack(fill="x", padx=16, pady=(2, 10))
        self.navbtn = {}
        # the topics scroll when the window is too short for all of them
        topics = ctk.CTkScrollableFrame(nav, fg_color="transparent", corner_radius=0)
        topics.pack(fill="both", expand=True, padx=(0, 2), pady=(0, 8))
        self.topics = topics
        for title, _ in HT.TOPICS:
            b = ctk.CTkButton(topics, text=title, anchor="w", height=30, corner_radius=8, font=font(12),
                              fg_color="transparent", hover_color=BORDER, text_color=TEXT,
                              command=lambda t=title: self.show(t))
            b.pack(fill="x", padx=(4, 2), pady=1)
            self.navbtn[title] = b
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=0, column=1, sticky="nsew", padx=(8, 8), pady=(8, 0))
        self.body.grid_columnconfigure(0, weight=1)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=1, column=1, sticky="ew", padx=8, pady=8)
        self.prev_b = button(foot, "Previous", lambda: self.step(-1), width=110, icon_name="left")
        self.prev_b.pack(side="left", padx=6)
        self.next_b = button(foot, "Next", lambda: self.step(1), width=110, icon_name="right")
        self.next_b.pack(side="left")
        button(foot, "Close", self.destroy, primary=True, width=100, height=32).pack(side="right", padx=6)
        self.current = None
        self._wrap, self._job = 0, None
        self.body.bind("<Configure>", self._resized, add="+")
        self.show(topic if topic in self.navbtn else HT.TOPICS[0][0])

    def _resized(self, e):
        w = max(360, units(e.width) - 60)
        if abs(w - self._wrap) > 30 and self.current:
            self._wrap = w
            if self._job:
                self.after_cancel(self._job)
            self._job = self.after(150, lambda: self.show(self.current, keep_scroll=True))

    def _nav_into_view(self, title):
        """Scroll the topic list so the open topic's button shows (Previous / Next, or opened at a topic)."""
        try:
            b = self.navbtn[title]
            cv = self.topics._parent_canvas
            total = max(1, b.master.winfo_height())
            top, bot = cv.yview()
            y0, y1 = b.winfo_y() / total, (b.winfo_y() + b.winfo_height()) / total
            if y0 < top:
                cv.yview_moveto(y0)
            elif y1 > bot:
                cv.yview_moveto(max(0.0, y1 - (bot - top)))
        except Exception:
            pass

    def step(self, d):
        names = [t for t, _ in HT.TOPICS]
        i = names.index(self.current) + d
        if 0 <= i < len(names):
            self.show(names[i])

    def show(self, title, keep_scroll=False):
        self.current = title
        for t, b in self.navbtn.items():
            b.configure(fg_color=ACCENT if t == title else "transparent",
                        text_color=WHITE if t == title else TEXT)
        self.after_idle(lambda: self._nav_into_view(title))
        for w in self.body.winfo_children():
            w.destroy()
        names = [t for t, _ in HT.TOPICS]
        i = names.index(title)
        self.prev_b.configure(state="normal" if i > 0 else "disabled")
        self.next_b.configure(state="normal" if i < len(names) - 1 else "disabled")
        blocks = dict(HT.TOPICS)[title]
        wrap = self._wrap or 640
        row = 0

        def put(w, py=(0, 8), px=14):
            nonlocal row
            w.grid(row=row, column=0, sticky="ew", padx=px, pady=py)
            row += 1

        put(ctk.CTkLabel(self.body, text=title, text_color=TEXT, font=font(22, "bold"), anchor="w"), (10, 10))
        for kind, val in blocks:
            if kind == "p":
                put(ctk.CTkLabel(self.body, text=val, text_color=TEXT, font=font(13), anchor="w", justify="left",
                                 wraplength=wrap))
            elif kind == "h":
                put(ctk.CTkLabel(self.body, text=val, text_color=TEXT, font=font(15, "bold"), anchor="w"), (8, 4))
            elif kind in ("steps", "bullets"):
                box = ctk.CTkFrame(self.body, fg_color="transparent")
                box.grid_columnconfigure(1, weight=1)
                for n, line in enumerate(val, 1):
                    mark = f"{n}." if kind == "steps" else "•"
                    ctk.CTkLabel(box, text=mark, text_color=ACCENT, font=font(13, "bold"), width=22, anchor="ne"
                                 ).grid(row=n, column=0, sticky="ne", padx=(0, 6), pady=2)
                    ctk.CTkLabel(box, text=line, text_color=TEXT, font=font(13), anchor="w", justify="left",
                                 wraplength=wrap - 30).grid(row=n, column=1, sticky="w", pady=2)
                put(box)
            elif kind == "tip":
                c = card(self.body)
                ctk.CTkLabel(c, text="  " + val, image=icon("info", 18, ACCENT), compound="left", text_color=TEXT,
                             font=font(12), anchor="w", justify="left", wraplength=wrap - 50
                             ).pack(fill="x", padx=12, pady=10)
                put(c, (4, 10))
            elif kind == "roles":
                box = ctk.CTkFrame(self.body, fg_color="transparent")
                box.grid_columnconfigure(1, weight=1)
                for n, (role, line) in enumerate(HT.role_lines()):
                    img = ctk_image(icons.badge(role, 40), (20, 20)) if icons.available() else None
                    ctk.CTkLabel(box, text="" if img else role.glyph, image=img, width=24
                                 ).grid(row=n, column=0, sticky="nw", padx=(0, 8), pady=3)
                    ctk.CTkLabel(box, text=line, text_color=TEXT, font=font(13), anchor="w", justify="left",
                                 wraplength=wrap - 40).grid(row=n, column=1, sticky="w", pady=3)
                put(box)
        if not keep_scroll:
            try:
                self.body._parent_canvas.yview_moveto(0)
            except Exception:
                pass


# ================================================================== main window
class App(ctk.CTk):
    def __init__(self):
        cfg = load_settings()
        ctk.set_appearance_mode(cfg.get("theme", "System"))     # before the window exists: no flash
        super().__init__(fg_color=BG, className="ParadoxicalLauncher")  # Linux menus
        self.withdraw()                        # shown once everything is ready (the loading screen covers it)
        set_root(self)
        self.cfg = cfg
        COLUMNS["cfg"], COLUMNS["save"] = cfg.setdefault("columns", {}), self.save   # dragged column widths
        self._prerender = False
        self.splash = Splash(self)
        self.splash.step("Preparing the interface...", 0.04)
        appicon.apply(self, APP_DIR)
        self.title(f"{APP_NAME} {APP_VERSION}")
        if cfg.get("geometry"):
            self.geometry(cfg["geometry"])
        else:
            fit_geometry(self, 1440, 900)
        sw, sh = units(self.winfo_screenwidth()), units(self.winfo_screenheight())
        self.minsize(int(min(920, sw * 0.9)), int(min(600, sh * 0.82)))
        self.report_callback_exception = self._tk_error
        self.registry_file, self.updates_file, self.work_dir = REGISTRY_FILE, UPDATES_FILE, WORK_DIR
        self.profiles = Profiles(PROFILES_FILE)
        self.q = queue.Queue()
        self.engine = None
        self.update_run = None          # {workshop id: [old copies]} while an update run is going
        self.pending = None             # saved queue of an unfinished run
        self.up_next = []               # workshop ids caught while a run was going: they start after it
        self.dl_state = {}              # workshop id -> (state, progress) of the current / last run
        self.run_total, self.run_done = 0, 0
        self.mods, self.mods_loaded, self.scan_token, self.scan_error = [], False, 0, ""
        self.updates, self.checked_at = {}, 0
        self.to_add = []                # freshly installed mods waiting for the next scan to join the playset
        self.analysis, self.analyzing, self.an_sig, self.an_token = None, False, None, 0
        self.an_progress = ""
        self._thumbs, self._wids, self._reg_cache = {}, None, None
        self.catch_list = load_catch_list()     # workshop id -> title, waiting to be caught (kept on disk)
        self.dep_check = set()          # workshop ids whose required mods are being looked up
        self.thumbs_dir = os.path.join(WORK_DIR, "thumbs")
        self.shots_dir = os.path.join(WORK_DIR, "shots")        # full-size screenshots (picture viewer)
        self._installs = {}
        self._last_error = 0
        self._browse_dirty_status = False
        self.settings_win = self.help_win = None
        self.bridge = BrowserBridge(on_event=lambda e: self.q.put(("bridge", e)),
                                    title=f"Site check - {APP_NAME}") if BrowserBridge.available() else None
        style_trees(self)
        self._build()
        try:
            ctk.AppearanceModeTracker.add(lambda mode: self.after(10, self._restyle), self)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Configure>", self._on_configure, add="+")
        self.after(100, self._drain)
        self._first_run = not self.cfg.get("welcome_done")
        if self.cfg.get("welcome_done"):
            self.after(30, self._boot)
        else:
            self.splash.withdraw()
            self.after(100, lambda: WelcomeWindow(self, self._welcomed))

    # ================================================================ layout
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        appbar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        appbar.grid(row=0, column=0, sticky="ew")
        appbar.grid_columnconfigure(0, weight=1)
        if COLORFUL:
            self.ribbon = Ribbon(self)
            self.ribbon.grid(row=1, column=0, sticky="ew")
        else:
            self.ribbon = None
            ctk.CTkFrame(self, fg_color=SHADOW, height=1, corner_radius=0).grid(row=1, column=0, sticky="ew")
        head = ctk.CTkFrame(appbar, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 0))
        head.grid_columnconfigure(1, weight=1)
        brand = ctk.CTkFrame(head, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w")
        try:
            self._logo = ctk_image(appicon.render(128), (40, 40))
            ctk.CTkLabel(brand, text="", image=self._logo).pack(side="left", padx=(0, 8))
        except Exception:
            pass
        self.name_lbl = ctk.CTkLabel(brand, text=APP_NAME, text_color=TEXT, font=font(19, "bold"))
        self.name_lbl.pack(side="left")
        self.ver_chip = ctk.CTkLabel(brand, text=APP_VERSION, text_color=MUTED, font=font(10, "bold"), fg_color=CARD,
                                     corner_radius=8, height=20, width=34)
        self.ver_chip.pack(side="left", padx=(8, 0), pady=(4, 0))

        ctl = ctk.CTkFrame(head, fg_color="transparent")
        ctl.grid(row=0, column=2, sticky="e")
        self.ctl = ctl
        self.ctl_labels = []

        def lbl(text, col, padx):
            w = ctk.CTkLabel(ctl, text=text, text_color=MUTED, font=font(11))
            w.grid(row=0, column=col, padx=padx)
            self.ctl_labels.append(w)
        lbl("Game", 0, (0, 4))
        self.detected = installer.detect_mod_dirs()
        self.game_menu = ctk.CTkOptionMenu(ctl, values=[OTHER_FOLDER], width=190, height=32, fg_color=CARD_HI,
                                           button_color=CARD_HI, button_hover_color=BORDER, text_color=TEXT,
                                           font=font(12, "bold"), dropdown_font=font(12), dynamic_resizing=False,
                                           command=self._pick_game, corner_radius=9)
        self.game_menu.grid(row=0, column=1)
        lbl("Version", 2, (10, 4))
        self.version_box = ctk.CTkComboBox(ctl, values=[""], width=88, height=32, fg_color=CARD_HI,
                                           border_color=BORDER, button_color=CARD_HI, button_hover_color=BORDER,
                                           text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
                                           font=font(12), corner_radius=9, dropdown_font=font(12),
                                           command=lambda v: self._version_changed())
        self.version_box.grid(row=0, column=3, padx=(6, 0))
        self.version_box._entry.bind("<Return>", lambda e: self._version_changed())
        self.version_box._entry.bind("<FocusOut>", lambda e: self._version_changed())
        lbl("Playset", 4, (12, 4))
        self.profile_menu = ctk.CTkOptionMenu(ctl, values=["-"], width=180, height=32, fg_color=CARD_HI,
                                              button_color=CARD_HI, button_hover_color=BORDER, text_color=TEXT,
                                              font=font(12), dropdown_font=font(12), dynamic_resizing=False,
                                              command=self.set_active_profile, corner_radius=9)
        self.profile_menu.grid(row=0, column=5, padx=(6, 0))
        Tooltip(self.game_menu, "The game whose mods you're working on")
        Tooltip(self.version_box, "The game version you play: mods made for another one get a quiet note")
        Tooltip(self.profile_menu, "The playset Play starts the game with")
        self.play_btn = ctk.CTkButton(ctl, text="Play", width=96, height=34, corner_radius=9, fg_color=PLAY,
                                      hover_color=PLAY_HI, text_color="white", font=font(13, "bold"), command=self.play,
                                      image=icon("play", 15, WHITE), compound="left")
        self.play_btn.grid(row=0, column=6, padx=(10, 0))
        self.play_more = ctk.CTkButton(ctl, text="", width=28, height=34, corner_radius=9, fg_color=PLAY,
                                       hover_color=PLAY_HI, command=self._play_menu, image=icon("down", 14, WHITE))
        self.play_more.grid(row=0, column=7, padx=(2, 12))
        Tooltip(self.play_btn, "Start the game with this playset")
        Tooltip(self.play_more, "More: continue the last save, debug mode, open folders and the error log")
        # tools that work from every tab: look through the mod folder again, ask the Workshop for updates
        self.tools = {}
        for col, (name, ic, tint, soft, tip, cmd) in enumerate((
                ("scan", "scan", TEAL, TEAL_SOFT, "Rescan: read the mod folder again (new, changed or removed "
                                                  "mods)", self.rescan),
                ("updates", "update", ACCENT, ACCENT_SOFT, "Check updates: ask the Workshop which of your mods "
                                                           "have a newer version", self.check_updates))):
            b = ctk.CTkButton(ctl, text="", width=34, height=32, corner_radius=9, fg_color=soft, hover_color=BORDER,
                              border_width=0, image=icon(ic, 17, tint), command=cmd)
            b.grid(row=0, column=8 + col, padx=(0, 4))
            Tooltip(b, tip)
            self.tools[name] = (b, ic, tint, soft)
        ctk.CTkFrame(ctl, width=1, height=22, fg_color=BORDER).grid(row=0, column=10, padx=(4, 8))
        self.theme_btn = button(ctl, "", self._toggle_theme, width=34, height=32, icon_name="moon",
                                tip="Light / dark look")
        self.theme_btn.grid(row=0, column=11, padx=(0, 4))
        button(ctl, "", self._open_help, width=34, height=32, icon_name="help",
               tip="Help: how every part of the app works").grid(row=0, column=12, padx=(0, 4))
        self.settings_btn = button(ctl, "Settings", self._open_settings, width=104, height=32, icon_name="settings",
                                   tip="Settings: download sites, accounts, games, look")
        self.settings_btn.grid(row=0, column=13)

        bar = ctk.CTkFrame(appbar, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 0))
        bar.grid_columnconfigure(1, weight=1)
        self.tabs = TabBar(bar, TABS, self.show_tab, TAB_ICONS)
        self.tabs.grid(row=0, column=0, sticky="w")
        self.run_lbl = ctk.CTkLabel(bar, text="", text_color=MUTED, font=font(11), anchor="e")
        self.run_lbl.grid(row=0, column=1, sticky="e", padx=(8, 8))
        self.run_bar = ctk.CTkProgressBar(bar, width=140, height=6, corner_radius=3, fg_color=CARD_HI,
                                          progress_color=ACCENT)
        self.run_bar.grid(row=0, column=2, sticky="e", padx=(0, 6))
        self.run_bar.grid_remove()
        self.banner = Banner(self)
        self.banner.grid(row=2, column=0, sticky="ew", padx=18, pady=(12, 0))
        self.banner.hide()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=3, column=0, sticky="nsew", padx=18, pady=(12, 12))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.splash.step("Building the Browse tab...", 0.08)
        self.browse = BrowsePage(body, self)
        self.splash.step("Building the Catch tab...", 0.11)
        self.catch = CatchPage(body, self)
        self.splash.step("Building the Library tab...", 0.14)
        self.library = LibraryPage(body, self)
        self.splash.step("Building the Playsets tab...", 0.17)
        self.playsets = PlaysetsPage(body, self)
        self.splash.step("Building the Conflicts tab...", 0.20)
        self.conflicts = ConflictsPage(body, self)
        self.crashes = CrashPage(body, self)
        self.pages = {"Browse": self.browse, "Catch": self.catch, "Library": self.library, "Playsets": self.playsets,
                      "Conflicts": self.conflicts, "Crashes": self.crashes}
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")

        ctk.CTkFrame(self, fg_color=SHADOW, height=1, corner_radius=0).grid(row=4, column=0, sticky="ew")
        status = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=28)
        status.grid(row=5, column=0, sticky="ew")
        status.grid_columnconfigure(1, weight=1)
        self.status_dot = ctk.CTkFrame(status, width=10, height=10, corner_radius=5, fg_color=OK)
        self.status_dot.grid(row=0, column=0, padx=(20, 8), pady=7)
        self.status_left = ctk.CTkLabel(status, text="", text_color=MUTED, font=font(11), anchor="w")
        self.status_left.grid(row=0, column=1, sticky="w")
        self.status_right = ctk.CTkLabel(status, text="", text_color=MUTED, font=font(11), anchor="e")
        self.status_right.grid(row=0, column=2, sticky="e", padx=(8, 20))
        self._fill_games()
        self._fill_versions()
        self._theme_label()
        self.show_tab(self.cfg.get("tab", "Browse"))
        self._compact = None
        self.after(60, lambda: self._responsive(self.winfo_width()))

    # ---- the header adapts to the window width
    def _on_configure(self, e):
        if e.widget is self and hasattr(self, "ctl"):
            self._responsive(e.width)

    def _apply_level(self, level):
        for w in self.ctl_labels:
            w.grid() if level == 0 else w.grid_remove()
        self.name_lbl.configure(text=APP_NAME if level < 2 else APP_SHORT, font=font(19 if level < 2 else 17, "bold"))
        self.ver_chip.pack(side="left", padx=(8, 0), pady=(4, 0)) if level < 2 else self.ver_chip.pack_forget()
        self.settings_btn.configure(text="Settings" if level <= 1 else "", width=104 if level <= 1 else 34)
        self.game_menu.configure(width=190 if level < 2 else 178)
        self.profile_menu.configure(width=180 if level < 2 else 150)

    def _responsive(self, width):
        """The header folds its labels, then shortens the name, so it always fits the window."""
        if width < 200:
            return
        if not getattr(self, "_need", None):
            self._need = {}
            for level in (0, 1, 2, 3):
                self._apply_level(min(level, 2))
                if level == 3:                        # the narrowest: also no field labels and no settings text
                    self.settings_btn.configure(text="", width=34)
                self.update_idletasks()
                self._need[level] = self.name_lbl.master.winfo_reqwidth() + self.ctl.winfo_reqwidth() + px(52)
            self._compact = None
        level = next((lv for lv in (0, 1, 2) if self._need[lv] <= width), 3)
        if level == self._compact:
            return
        self._compact = level
        self._apply_level(min(level, 2))
        if level == 3:
            self.settings_btn.configure(text="", width=34)

    def visible(self, name):
        return self._prerender or self.tabs.get() == name

    def show_tab(self, name):
        self.tabs.set(name)
        if self.ribbon is not None:
            self.ribbon.set_tab(name)
        page = self.pages[name]
        page.tkraise()
        if hasattr(page, "on_show"):
            page.on_show()
        if self.cfg.get("tab") != name:
            self.cfg["tab"] = name
            self.save()

    def _restyle(self):
        style_trees(self)
        for t in (self.catch.queue, self.catch.clist, self.library.table, self.playsets.order, self.playsets.extra,
                  self.playsets.plist, self.conflicts.table):
            t.restyle()
        for s in Split.instances:
            s.restyle()
        for page in (self.library, self.playsets):
            page.dp.restyle()
        self.conflicts.dp.restyle()
        self.crashes.restyle()
        self.browse.restyle()
        self._theme_label()

    def tool_busy(self, name, busy):
        """A top-bar tool is working (or can't run right now): it greys out until it's free again."""
        b, ic, tint, soft = self.tools[name]
        b.configure(state="disabled" if busy else "normal", fg_color=MUTED_SOFT if busy else soft,
                    image=icon(ic, 17, FAINT if busy else tint))

    def check_updates(self):
        if not self.mods:
            self.toast("No mods to check yet.", color=MUTED)
            return
        self.library.check_updates()

    # ================================================================ errors never stop the app
    def _tk_error(self, exc, val, tb):
        self._report("".join(traceback.format_exception(exc, val, tb)), val)

    def _report(self, text, val=None):
        error_log(APP_DIR, text)
        try:
            self.catch.log("Unexpected error: " + str(val or text.strip().splitlines()[-1]))
        except Exception:
            pass
        if time.time() - self._last_error > 8:
            self._last_error = time.time()
            try:
                self.banner.show(f"{WARN_ICON}  Something went wrong ({val or 'see the log'}). The app carries on; "
                                 "details are in .work\\errors.log.", kind="error", color=ERR,
                                 actions=[("Close", lambda: self.banner.hide("error"))])
            except Exception:
                pass

    # ================================================================ helpers used by the pages
    def save(self):
        save_settings(self.cfg)

    def log(self, msg):
        self.catch.log(msg)

    def registry(self):
        """installed.json (what this app installed, from where), read again only when the file changes."""
        try:
            mt = os.path.getmtime(REGISTRY_FILE)
        except OSError:
            mt = 0
        if self._reg_cache is None or self._reg_cache[0] != mt:
            self._reg_cache = (mt, installer.load_registry(REGISTRY_FILE))
        return self._reg_cache[1]

    def thumb(self, m):
        """Path of the best picture for a mod ('' if none), cached per scan."""
        key = (m.key, self.scan_token)
        if key not in self._thumbs:
            self._thumbs[key] = icons.thumb_file(m, U.workshop_id(m, self.registry()), self.thumbs_dir) \
                if icons.available() else ""
        return self._thumbs[key]

    def installed_wids(self):
        """{workshop id: ModInfo} of what's installed (by registry, remote_file_id or file name)."""
        if self._wids is None or self._wids[0] is not self.mods:
            reg = self.registry()
            out = {}
            for m in self.mods:
                wid = U.workshop_id(m, reg)
                if wid and not m.missing:
                    out[wid] = m
            self._wids = (self.mods, out)
        return self._wids[1]

    def steam_ok(self):
        return steam_allowed(self.cfg, self.game())

    def effective_enabled(self):
        en = dict(self.cfg["enabled"])
        en["steam"] = self.steam_ok()
        return en

    # ---- the catch list (Browse adds to it; the Catch tab shows it)
    def catch_list_changed(self):
        save_catch_list(self.catch_list)
        self.browse._render_list()
        self.browse.refresh_status()
        self.catch.render_list()

    def add_to_catch_list(self, items):
        """items: {workshop id: title}"""
        for wid, title in items.items():
            self.catch_list[wid] = title
        self.catch_list_changed()

    def add_links_to_list(self, ids):
        """Workshop links (mods or collections) go to the catch list, not straight to downloading. A
        collection is opened up into its mods; names come from Steam in the background."""
        ids = [i for i in dict.fromkeys(ids) if i]
        if not ids:
            return
        for wid in ids:
            self.catch_list.setdefault(wid, self.catch_list.get(wid) or self.browse_title(wid) or f"Workshop item {wid}")
        self.dep_check |= set(ids)
        self.catch_list_changed()
        self.toast(f"Added {len(ids)} link{'s' if len(ids) != 1 else ''} to the catch list. Press Download all "
                   "when you're ready.", color=ACCENT)

        def work():
            import net as N
            names, kids = {}, {}
            try:
                net = N.Net()
                kids = S.steam_collection_children(net, ids)
                every = list(ids) + [c for cs in kids.values() for c in cs]
                names = {k: (d.get("title") or "") for k, d in S.steam_details(net, every).items()}
            except Exception:
                pass
            self.q.put(("links_resolved", ids, names, kids))
        threading.Thread(target=work, daemon=True).start()

    def _links_resolved(self, ids, names, kids):
        self.dep_check -= set(ids)
        for wid in ids:
            if wid not in self.catch_list:
                continue                               # removed meanwhile
            if kids.get(wid):                          # a collection: its mods take its place
                self.catch_list.pop(wid, None)
                for c in kids[wid]:
                    self.catch_list.setdefault(c, names.get(c) or f"Workshop item {c}")
                self.log(f"Collection \"{names.get(wid) or wid}\": {len(kids[wid])} mods added to the catch list.")
            elif names.get(wid):
                self.catch_list[wid] = names[wid]
        self.catch_list_changed()

    def update_jobs_for(self, ids):
        """{workshop id: old copies} for the ids that are installed and have a newer version: those are
        updates, not mods to skip because they're already there."""
        reg = self.registry()
        jobs = {}
        want = set(ids)
        for m in self.mods:
            if not self.updates.get(m.key, {}).get("update"):
                continue
            wid = self.updates.get(m.key, {}).get("id") or U.workshop_id(m, reg)
            if wid in want:
                jobs.setdefault(wid, [])
        for wid in jobs:
            jobs[wid] = [{"modfile": o.modfile, "folder": o.folder} for o in self.mods if U.workshop_id(o, reg) == wid]
        return jobs

    def remove_from_catch_list(self, ids):
        for wid in ids:
            self.catch_list.pop(wid, None)
        self.catch_list_changed()

    def catch_from_list(self, ids=None):
        """Download mods from the catch list (all of them by default). They stay listed until installed."""
        ids = [i for i in (ids or list(self.catch_list)) if not self.list_state(i)[0].startswith("↓")]
        if ids:
            self.catch_ids(ids)

    def list_state(self, wid):
        """(status text, tree tag) of a catch-list mod."""
        if wid in self.dep_check:
            return "Checking...", "muted"
        st = self.dl_state.get(wid)
        if st and st[0] == "Working":
            return (f"↓ {int(st[1] * 100)}%" if st[1] is not None else "↓ Working"), "update"
        if st and st[0] == "Queued":
            return "↓ Queued", "update"
        if wid in self.up_next:
            return "↓ Up next", "update"
        if st and st[0] in ("Not found", "Interrupted", "Stopped"):
            return {"Not found": "✗ Not found", "Interrupted": "✗ Failed", "Stopped": "Stopped"}[st[0]], "missing"
        if st and st[0] == "Paused":
            return "Paused", "conflict"
        return "Waiting", ""

    def browse_title(self, wid):
        it = self.browse.items.get(wid)
        return it.title if it else ""

    def retry_ids(self, ids):
        """Try downloads that didn't work again (nothing asked: they were chosen already)."""
        self.catch_ids(ids, deps=False)

    # ---- catching from other tabs
    def catch_ids(self, ids, show_catch=False, deps=True):
        """Download these Workshop IDs now, or right after the current run. First, when a mod needs other
        Workshop mods you don't have (or have in an older version), you're asked whether to catch them too."""
        ids = [i for i in dict.fromkeys(ids) if i]
        if not ids:
            return
        if deps and self.cfg.get("ask_deps", True):
            self._check_deps(ids, show_catch)
            return
        self._catch_now(ids, show_catch)

    def _check_deps(self, ids, show_catch):
        token = getattr(self, "_dep_token", 0) + 1
        self._dep_token = token
        self.dep_check |= set(ids)
        self.catch.refresh_list()
        have = dict(self.installed_wids())
        reg = self.registry()
        mine = {}
        for wid, m in have.items():
            mine[wid] = (reg.get(wid, {}) or {}).get("steam_updated") or int(m.installed_at or 0)

        def work():
            import net as N
            import workshop as W
            net = N.Net()
            need, names, seen, frontier = {}, {}, set(ids), list(ids)
            for _ in range(3):                         # mods needed by the needed mods, three levels deep
                nxt = []
                for wid in frontier:
                    try:
                        req = W.details(net, wid).required
                    except Exception:
                        req = []
                    for rid, name in req:
                        names[rid] = name
                        if rid not in seen:
                            seen.add(rid)
                            nxt.append(rid)
                            need.setdefault(rid, wid)
                frontier = nxt
                if not frontier:
                    break
            info = {}
            if need:
                try:
                    info = S.steam_details(net, list(need))
                except Exception:
                    info = {}
            out = []
            for rid, by in need.items():
                d = info.get(rid) or {}
                title = d.get("title") or names.get(rid) or rid
                if rid in have:
                    upd = int(d.get("time_updated", 0) or 0)
                    if upd and mine.get(rid) and upd > mine[rid] + U.SLACK:
                        out.append((rid, title, "update", by))
                else:
                    out.append((rid, title, "missing", by))
            self.q.put(("deps", token, ids, out, show_catch))
        threading.Thread(target=work, daemon=True).start()

    def _deps_found(self, token, ids, needed, show_catch):
        if token != getattr(self, "_dep_token", 0):
            return
        self.dep_check -= set(ids)
        self.catch.refresh_list()
        if not needed:
            self._catch_now(ids, show_catch)
            return
        DepsDialog(self, ids, needed, lambda choice: self._deps_chosen(choice, ids, needed, show_catch))

    def _deps_chosen(self, choice, ids, needed, show_catch):
        if choice == "cancel":
            return
        if choice == "only":
            self._catch_now(ids, show_catch)
            return
        missing = [rid for rid, _, kind, _ in needed if kind == "missing"]
        updates = [rid for rid, _, kind, _ in needed if kind == "update"]
        jobs = {}
        if updates:
            reg = self.registry()
            for wid in updates:
                jobs[wid] = [{"modfile": o.modfile, "folder": o.folder} for o in self.mods
                             if U.workshop_id(o, reg) == wid]
        self._catch_now(missing + list(ids) + updates, show_catch, update_jobs=jobs)

    def _catch_now(self, ids, show_catch=False, update_jobs=None):
        ids = [i for i in dict.fromkeys(ids) if i]
        if not ids:
            return
        auto = self.update_jobs_for(ids)             # caught mods that need an update are updated, not skipped
        if auto:
            update_jobs = dict(auto, **(update_jobs or {}))
        if self.running():
            have = {it for it in self.dl_state if self.dl_state[it][0] in ("Queued", "Working")}
            new = [i for i in ids if i not in self.up_next and i not in have]
            self.up_next += new
            self._refresh_browse_status()
            self._run_status()
            if new:
                self.toast(f"Up next: {len(self.up_next)} mod{'s' if len(self.up_next) != 1 else ''}. They start "
                           "as soon as the current downloads finish.", color=ACCENT)
            return
        resume = None
        if self.pending:
            ans = messagebox.askyesnocancel(APP_NAME, f"{self._pending_count()} unfinished download(s) from before "
                                                      "are waiting. Continue them in this run too?\n\nNo throws "
                                                      "them away.", parent=self)
            if ans is None:
                return
            if ans:
                resume = self.pending
            else:
                E.discard_queue(WORK_DIR)
            self.pending = None
        if show_catch:
            self.show_tab("Catch")
        else:
            self.toast(f"Catching {len(ids)} mod{'s' if len(ids) != 1 else ''}. Progress shows here and in the "
                       "Catch tab.", color=ACCENT)
        if update_jobs and not resume:
            self.update_run = update_jobs
            self._launch(ids, {"force_ids": list(update_jobs), "replace": update_jobs})
            return
        self._launch(ids, resume=resume)

    def show_issue(self, issue):
        """The Conflicts tab with this conflict selected."""
        self.show_tab("Conflicts")
        self.conflicts.focus_issue(issue)

    def crash_note(self, key):
        """(text, crash) when this mod is a likely or possible suspect of the newest crash, else None."""
        r = self.crashes.latest_result() if hasattr(self, "crashes") else None
        s = r.suspect(key) if r else None
        if s is None or s.sure == "unlikely":
            return None
        when = time.strftime("%d %b %H:%M", time.localtime(r.crash.when))
        return (f"{'A likely' if s.sure == 'likely' else 'A possible'} suspect in the crash of {when}: "
                f"{s.reasons[0][1] if s.reasons else ''}", r.crash)

    def show_crash_suspect(self, key):
        self.show_tab("Crashes")
        cp = self.crashes
        if cp.crashes and cp.current is not cp.crashes[0]:
            cp.show(cp.crashes[0])
        t = cp.table.tree
        rid = next((rid for rid, s in cp.by_row.items() if s.key == key), None)
        if rid:
            t.selection_set(rid)
            t.see(rid)

    def crash_badge(self):
        cp = getattr(self, "crashes", None)
        n = len(cp.unseen()) if cp is not None else 0
        self.tabs.set_badge("Crashes", n or "", CRIT)

    def _crash_banner(self):
        cp = self.crashes
        new = cp.unseen()
        if not new or self.cfg.get("crash_hunt"):
            return
        c = new[0]
        when = time.strftime("%d %b at %H:%M", time.localtime(c.when))
        self.banner.show(f"The game crashed on {when}" + (f" ({len(new)} crashes you haven't looked at)"
                                                          if len(new) > 1 else "") + ". See what likely caused it.",
                         actions=[("Show the crash", lambda: (self.banner.hide("crash"), self.show_tab("Crashes"))),
                                  ("Later", lambda: self.banner.hide("crash"))], kind="crash", tone="warn")

    def show_conflicts_for(self, key):
        self.show_tab("Conflicts")
        self.conflicts.focus_on(key)

    def show_in_playset(self, key):
        self.show_tab("Playsets")
        self.playsets.select_key(key)

    def show_in_library(self, key):
        self.show_tab("Library")
        self.library.select_key(key)

    def show_in_browse_search(self, text):
        self.show_tab("Browse")
        self.browse.search_for(text)

    def conflicts_changed(self):
        """The active playset (or the analysis) changed: refresh the Conflicts tab and the counters."""
        self.conflicts.render()
        self._tab_info()

    def _tab_info(self):
        mods = self.mods
        ps = self.playsets
        bits = [f"{len(mods)} mod{'s' if len(mods) != 1 else ''} installed"]
        if ps.name:
            bits.append(f"playset \"{ps.name}\": {len(ps.enabled_keys())} on")
        c = A.summary(self.conflicts.counted_issues()) if self.analysis is not None and ps.name else None
        if c is not None:
            bad = [f"{n} {w}" for n, w in ((c["critical"], "critical"), (c["high"], "high")) if n]
            bits.append(f"{', '.join(bad)} conflict{'s' if sum((c['critical'], c['high'])) != 1 else ''}" if bad
                        else "no serious conflicts")
        self.status_left.configure(text="  ·  ".join(bits))
        bad = c is not None and (c["critical"] or c["high"])
        self.status_dot.configure(fg_color=(CRIT if c and c["critical"] else WARN) if bad else
                                  (ACCENT if self.analyzing else OK))
        self.status_right.configure(text=(f"Analysing your mods: {self.an_progress}..." if self.analyzing and
                                          self.an_progress else ("Analysing your mods..." if self.analyzing else "")))
        # tab counters
        n_up = sum(1 for m in mods if self.updates.get(m.key, {}).get("update"))
        self.tabs.set_badge("Library", n_up or "", ACCENT)
        if c is not None and (c["critical"] or c["high"]):
            self.tabs.set_badge("Conflicts", c["critical"] + c["high"], CRIT if c["critical"] else WARN)
        else:
            self.tabs.set_badge("Conflicts", "")

    def _run_status(self):
        """The download counter next to the tabs and on the Catch tab."""
        if self.running():
            left = max(0, self.run_total - self.run_done)
            txt = f"Downloading: {self.run_done} of {self.run_total} done" if self.run_total else "Looking up mods..."
            if self.up_next:
                txt += f"  ·  {len(self.up_next)} up next"
            self.run_lbl.configure(text=txt, text_color=TEXT)
            self.run_bar.grid()
            self.run_bar.set(self.run_done / self.run_total if self.run_total else 0)
            self.tabs.set_badge("Catch", (left + len(self.up_next)) or "", ACCENT)
        else:
            self.run_bar.grid_remove()
            n = self._pending_count()
            self.run_lbl.configure(text=f"{n} download{'s' if n != 1 else ''} paused" if n else "", text_color=WARN)
            self.tabs.set_badge("Catch", n or "", WARN)

    # ================================================================ analysis (all installed mods)
    def schedule_analysis(self, force=False):
        """Read every installed mod once: roles, what each defines and uses, every pair that collides.
        Playsets then just look at the pairs they contain. Re-runs only when the mods change."""
        md = self.mod_dir()
        if not md or not self.mods_loaded:
            return
        sig = (md, self.scan_token, self.cfg.get("workshop_hints", True), self.game_install())
        if sig == self.an_sig and not force:
            return
        self.an_sig = sig
        self.an_token += 1
        token = self.an_token
        mods = list(self.mods)
        game_dir = self.game_install()
        reg = self.registry()
        wids = {m.key: U.workshop_id(m, reg) for m in mods}
        hints = self.cfg.get("workshop_hints", True)
        thumbs_dir = self.thumbs_dir
        self.analyzing, self.an_progress = True, ""
        self._tab_info()

        def work():
            try:
                import net as N
                net = N.Net()
                meta = A.load_workshop(net, [w for w in wids.values() if w],
                                       os.path.join(WORK_DIR, "workshop_pages.json"))
                used_meta = meta if hints else {}
                sig = self._analysis_signature(mods, game_dir, used_meta, wids)
                an = self._cached_analysis(sig, mods)
                if an is None:
                    an = A.analyze(mods, game_dir, used_meta, wids, cache_dir=WORK_DIR,
                                   progress=lambda txt, p: self.q.put(("an_progress", token, txt)))
                    self._store_analysis(sig, an)
                self.q.put(("analysis", token, an, ""))
                if icons.available():                 # pictures for mods that don't ship their own
                    by_key = {m.key: m for m in mods}
                    want = {w: (meta.get(w) or {}).get("preview", "") for k, w in wids.items()
                            if w and not icons.thumb_file(by_key[k])}
                    if icons.fetch_previews(net, want, thumbs_dir):
                        self.q.put(("thumbs",))
            except Exception as e:
                error_log(APP_DIR, traceback.format_exc())
                self.q.put(("analysis", token, None, f"{type(e).__name__}: {e}"))
        threading.Thread(target=work, daemon=True).start()

    ANALYSIS_CACHE_VERSION = 6

    @staticmethod
    def _analysis_signature(mods, game_dir, meta, wids):
        """Everything the analysis depends on: when none of it changed, last time's result is reused."""
        h = hashlib.sha1()
        h.update(f"v{App.ANALYSIS_CACHE_VERSION}|{game_dir}|".encode())
        if game_dir:
            try:
                h.update(LA.installed_version(game_dir).encode())
            except Exception:
                pass
        for m in sorted(mods, key=lambda m: m.key):
            try:
                mf = os.path.getmtime(m.modfile) if m.modfile else 0
            except OSError:
                mf = 0
            h.update(f"|{m.key}|{m.folder}|{m.size}|{len(m.files)}|{m.mtime}|{mf}".encode("utf-8", "replace"))
        for w in sorted(x for x in wids.values() if x):
            d = meta.get(w) or {}
            h.update(f"|{w}|{d.get('title', '')}|{len(d.get('text', ''))}|{','.join(d.get('tags', []))}"
                     .encode("utf-8", "replace"))
        return h.hexdigest()

    @staticmethod
    def _cached_analysis(sig, mods):
        try:
            with open(os.path.join(WORK_DIR, "analysis_cache.pkl"), "rb") as f:
                data = pickle.load(f)
            if data.get("sig") != sig:
                return None
            an = data["an"]
            by_key = {m.key: m for m in mods}
            for k, fct in an.facts.items():          # point at this session's mod objects
                if k in by_key:
                    fct.mod = by_key[k]
            an.seconds = 0.0
            an.from_cache = True
            return an
        except Exception:
            return None

    @staticmethod
    def _store_analysis(sig, an):
        try:
            os.makedirs(WORK_DIR, exist_ok=True)
            tmp = os.path.join(WORK_DIR, "analysis_cache.pkl.tmp")
            with open(tmp, "wb") as f:
                pickle.dump({"sig": sig, "an": an}, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, os.path.join(WORK_DIR, "analysis_cache.pkl"))
        except Exception:
            error_log(APP_DIR, "Couldn't save the analysis cache:\n" + traceback.format_exc())

    def _analysis_done(self, token, an, error):
        if token != self.an_token:
            return
        self.analyzing = False
        if error:
            self.log(f"Mod analysis failed: {error}")
            self.toast(f"Couldn't analyse the mods ({error})", color=WARN)
            self._tab_info()
            return
        self.analysis = an
        self.apply_role_overrides()
        self.log((f"Analysis of {len(an.facts)} mods loaded from the cache (nothing changed)"
                  if getattr(an, "from_cache", False) else f"Analysed {len(an.facts)} mods in {an.seconds:.1f}s")
                 + ("" if an.used_vanilla else " (game folder unknown: set it in Settings for a deeper check)") + ".")
        self.library.refresh_view()
        self.playsets.analysis_ready()
        self.conflicts_changed()
        self.crashes.reanalyse()

    def _thumbs_ready(self):
        self._thumbs.clear()
        self.library.render()
        self.playsets.render_order()

    def toast(self, msg, color=OK, action=None):
        self.log(msg)
        if action:
            self.banner.show(msg, kind="toast", color=color, actions=[action])
        else:
            self.banner.show(msg, kind="toast", color=color)
        self._toast_n = getattr(self, "_toast_n", 0) + 1
        n = self._toast_n
        self.after(6500, lambda: self.banner.hide("toast") if n == self._toast_n else None)

    def mod_dir(self):
        return (self.cfg.get("mod_dir") or "").strip()

    def game(self):
        d = self.mod_dir()
        return installer.game_of_mod_dir(d) if d else ""

    def game_version(self):
        return self.cfg.get("game_versions", {}).get(os.path.normcase(self.mod_dir()), "")

    def found_install(self, game):
        if game not in self._installs:
            try:
                found = LA.find_installs(game)
            except Exception:
                found = []
            self._installs[game] = found[0] if found else ""
        return self._installs[game]

    def game_install(self):
        game = self.game()
        if not game:
            return ""
        d = self.cfg.get("game_dirs", {}).get(game, "")
        if d and os.path.isdir(d):
            return d
        return self.found_install(game)

    def running(self):
        return self.engine is not None

    def playset_keys(self):
        """(keys in the active playset, keys turned on in it)"""
        e = self.playsets.entries
        return {k for k, _ in e}, {k for k, on in e if on}

    def add_to_playset(self, keys):
        self.playsets.add_keys(keys)
        self.toast(f"Added to playset \"{self.playsets.name}\".")

    def remove_from_playset(self, keys):
        self.playsets.remove_keys(keys)
        self.toast(f"Removed from playset \"{self.playsets.name}\".", color=MUTED)

    def forget_in_playsets(self, keys):
        md = self.mod_dir()
        if md:
            self.profiles.forget_keys(md, keys)
            self.playsets.entries = [(k, on) for k, on in self.playsets.entries if k not in set(keys)]

    def set_active_profile(self, name):
        if name and name != "-":
            self.playsets.activate(name)

    def header_profiles(self, names, active):
        self.profile_menu.configure(values=names or ["-"])
        self.profile_menu.set(active or "-")
        self.library.fill_playsets()
        if self.library.pset_filter.get() != "All mods":
            self.library.render()

    # ---- roles you set yourself (Library > right-click > Role)
    def role_overrides(self):
        return self.cfg.setdefault("role_overrides", {}).setdefault(os.path.normcase(self.mod_dir()), {})

    def apply_role_overrides(self):
        an = self.analysis
        if an is None:
            return
        import roles as R
        ov = self.role_overrides()
        for k, f in an.facts.items():
            auto = getattr(f, "role_auto", None) or f.role
            f.role_auto = auto
            rid = ov.get(k)
            if rid in R.BY_ID and auto is not None:
                f.role = R.RoleResult(R.BY_ID[rid], "set by you", [x for x in auto.secondary if x.id != rid],
                                      auto.focus, auto.attrs, auto.evidence, manual=True)
            else:
                f.role = auto

    def set_role(self, keys, rid):
        """rid: a role id, or None to go back to the automatic one."""
        ov = self.role_overrides()
        for k in keys:
            if rid:
                ov[k] = rid
            else:
                ov.pop(k, None)
        self.save()
        self.apply_role_overrides()
        self.library.render()
        self.playsets.render_all()
        self.toast("Role set." if rid else "Back to the automatic role.", color=MUTED)

    def launcher_playsets(self):
        """The official Paradox launcher's playsets for this game (read-only, re-read when the file changes)."""
        md = self.mod_dir()
        db = os.path.join(LA.data_dir_of(md), "launcher-v2.sqlite") if md else ""
        try:
            mt = os.path.getmtime(db) if db else 0
        except OSError:
            mt = 0
        if not mt:
            return []
        c = getattr(self, "_lp_cache", None)
        if c and c[0] == (db, mt):
            return c[1]
        try:
            got = LA.read_playsets(db)
        except Exception:
            got = []
        self._lp_cache = ((db, mt), got)
        return got

    def open_mod_dir(self):
        d = self.mod_dir() or self.cfg["other_dir"]
        os.makedirs(d, exist_ok=True)
        open_folder(d)

    # ================================================================ game + version
    def _fill_games(self):
        names = [g for g, _ in self.detected]
        cur = self.game()
        if cur and cur not in names:
            names.append(cur)
        self.game_menu.configure(values=names + [OTHER_FOLDER])
        self.game_menu.set(cur or (os.path.basename(self.mod_dir()) if self.mod_dir() else "Choose..."))

    def _pick_game(self, name):
        if name == OTHER_FOLDER:
            d = filedialog.askdirectory(title="Choose a mod folder (" + DATA_HINT.split(" (")[0] + ("\\mod)" if IS_WIN else "/mod)"),
                                        initialdir=self.mod_dir() or installer.documents_dir())
            if not d:
                self._fill_games()
                return
            self.set_mod_dir(os.path.normpath(d))
            return
        for g, path in self.detected:
            if g == name:
                self.set_mod_dir(path)

    def ask_steam_owned(self, game):
        """First time a game is picked: does the user own it on Steam? (Steam is skipped for it if not)"""
        if not game or game in self.cfg.setdefault("steam_owned", {}):
            return
        hint = f"\n\n{game} was found in your Steam library." if LA.on_steam(game) else ""
        own = messagebox.askyesno(APP_NAME, f"Do you own {game} on Steam?\n\nSteam only hands out Workshop mods to "
                                            "accounts that own the game. If you don't, Steam is skipped for this game "
                                            "and mods come from the other sites." + hint, parent=self)
        self.cfg["steam_owned"][game] = bool(own)
        self.save()
        self.catch.draw_chain_strip()

    def set_mod_dir(self, d):
        if d == self.mod_dir():
            self._fill_games()
            return
        self.cfg["mod_dir"] = d
        self.save()
        self._fill_games()
        self._fill_versions()
        self.mods, self.mods_loaded, self.updates, self.checked_at = [], False, {}, 0
        self.analysis, self.an_sig = None, None
        self.ask_steam_owned(self.game())
        self.catch.draw_chain_strip()
        self.browse.game_changed()
        self.rescan()

    def _fill_versions(self):
        game = self.game()
        vals = V.versions_for(game) or [""]
        self.version_box.configure(values=vals)
        cur = self.cfg.get("game_versions", {}).get(os.path.normcase(self.mod_dir()), "")
        if not cur and game:
            inst = self.game_install()
            cur = ".".join(LA.installed_version(inst).split(".")[:2]) if inst else ""
            if cur:                      # the game tells us which version is installed
                self.cfg.setdefault("game_versions", {})[os.path.normcase(self.mod_dir())] = cur
                self.save()
        self.version_box.set(V.clean(cur))

    def _version_changed(self):
        d = self.mod_dir()
        if not d:
            return
        v = V.clean(self.version_box.get())
        if self.version_box.get() != v:
            self.version_box.set(v)
        store = self.cfg.setdefault("game_versions", {})
        if store.get(os.path.normcase(d), "") != v:
            store[os.path.normcase(d)] = v
            self.save()
            self.library.refresh_view()
            self.playsets.refresh_derived()
            self.playsets.render_order()
            self.conflicts_changed()
            self.browse.version_changed()

    # ================================================================ scanning
    def rescan(self):
        md = self.mod_dir()
        self.scan_token += 1
        token = self.scan_token
        cache = U.load_cache(UPDATES_FILE, md) if md else {}
        self.updates, self.checked_at = cache.get("mods", {}), cache.get("checked_at", 0)
        if not md or not os.path.isdir(md):
            self.mods, self.mods_loaded, self.scan_error = [], bool(md), ""
            self._wids = None
            self.library.refresh_view()
            self.playsets.load()
            self.browse.installed_changed()
            self._tab_info()
            return
        self.library.summary.configure(text="Scanning...", text_color=MUTED)
        self.tool_busy("scan", True)
        ignored = set(self.cfg.get("ignored_mods", {}).get(os.path.normcase(md), []))

        def work():
            try:
                mods, n = modscan.scan(md, ignored=ignored)
                self.q.put(("scan", token, md, mods, ""))
            except Exception as e:
                error_log(APP_DIR, traceback.format_exc())
                self.q.put(("scan", token, md, [], f"{type(e).__name__}: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _scanned(self, token, md, mods, error):
        if token != self.scan_token or md != self.mod_dir():
            return
        self.tool_busy("scan", False)
        first = not self.mods_loaded or getattr(self.playsets, "loaded_for", None) != md
        self.mods, self.mods_loaded, self.scan_error = mods, True, error
        self._thumbs.clear()
        self._wids = None                     # what's installed changed: asked again from the new list
        self.library.refresh_view()
        if first:
            self.playsets.loaded_for = md
            self.playsets.load()
        else:
            self.playsets.refresh_derived()
            self.playsets.render_all()
        if self.to_add:
            have = {m.key for m in mods}
            keys = [k for k in self.to_add if k in have]
            self.to_add = []
            if keys and self.playsets.name:
                listed = {k for k, _ in self.playsets.entries}
                new = [k for k in keys if k not in listed]
                if new:
                    self.playsets.add_keys(new)
                    self.toast(f"Added {len(new)} new mod{'s' if len(new) != 1 else ''} to playset "
                               f"\"{self.playsets.name}\" (at the bottom; Auto-sort can place them).")
        self.browse.installed_changed()
        self.schedule_analysis()
        self._tab_info()

    # ================================================================ play
    def _play_menu(self):
        m = tk.Menu(self, tearoff=0, bg=pick(CARD), fg=pick(TEXT), activebackground=pick(ACCENT),
                    activeforeground="white", selectcolor=pick(TEXT))
        self._v_cont = tk.BooleanVar(value=self.cfg.get("play_continue", False))
        self._v_dbg = tk.BooleanVar(value=self.cfg.get("play_debug", False))
        m.add_checkbutton(label="Continue the last save", variable=self._v_cont,
                          command=lambda: self._set_play("play_continue", self._v_cont.get()))
        m.add_checkbutton(label="Debug mode (console, error log)", variable=self._v_dbg,
                          command=lambda: self._set_play("play_debug", self._v_dbg.get()))
        m.add_separator()
        m.add_command(label="Only set the mod list (don't start the game)", command=lambda: self.play(start=False))
        m.add_command(label="Open the game's install folder", command=lambda: self.game_install() and open_folder(self.game_install()))
        m.add_command(label="Open the mod folder", command=self.open_mod_dir)
        m.add_command(label="Open the game's error log", command=self._open_error_log)
        m.tk_popup(self.play_more.winfo_rootx(), self.play_more.winfo_rooty() + self.play_more.winfo_height())

    def _set_play(self, key, val):
        self.cfg[key] = bool(val)
        self.save()

    def _open_error_log(self):
        p = os.path.join(LA.data_dir_of(self.mod_dir()), "logs", "error.log") if self.mod_dir() else ""
        if p and os.path.isfile(p):
            open_folder(p)
        else:
            self.toast("No error log yet (the game writes one while it runs).", color=MUTED)

    def _ask_install(self, game):
        messagebox.showinfo(APP_NAME, f"Where is {game} installed?\n\nIt wasn't found in Steam's or GOG's "
                                      "records. Pick the game's install folder (the one with the 'launcher' or "
                                      "'binaries' folder).", parent=self)
        d = filedialog.askdirectory(parent=self, title=f"{game} install folder")
        if not d:
            return ""
        d = os.path.normpath(d)
        if not LA.looks_like_install(game, d):
            messagebox.showwarning(APP_NAME, f"{d}\ndoesn't look like a {game} install.", parent=self)
            return ""
        self.cfg.setdefault("game_dirs", {})[game] = d
        self.save()
        return d

    def play(self, start=True):
        md, game = self.mod_dir(), self.game()
        if not md or not game:
            messagebox.showinfo(APP_NAME, "Pick your game at the top first.", parent=self)
            return
        if not LA.game_info(game).get("load"):
            messagebox.showinfo(APP_NAME, f"Starting {game} with a playset isn't supported.", parent=self)
            return
        ps = self.playsets
        if not ps.name:
            messagebox.showinfo(APP_NAME, "Make a playset first (Playsets tab).", parent=self)
            return
        have = {m.key: m for m in self.mods}
        keys = [k for k, on in ps.entries if on and k in have]
        missing = [k for k, on in ps.entries if on and k not in have]
        issues = []
        if missing:
            issues.append(f"{len(missing)} mod(s) in the playset aren't installed and will be skipped.")
        for i in ps.issues:
            if i.severity == "critical":
                issues.append(f"{i.title}.")
        gv = self.game_version()
        off = [have[k].name for k in keys if V.compatible(have[k].supported, gv) is False]
        if off:
            issues.append(f"{len(off)} mod(s) were made for another game version (they usually still work).")
        if self.running():
            issues.append("Downloads are still running; mods that finish later join the next start.")
        if issues and start and not messagebox.askyesno(APP_NAME, f"Start {game} with \"{ps.name}\"?\n\n"
                                                                  + "\n".join("• " + i for i in issues[:8]),
                                                         parent=self):
            return
        inst = self.game_install() if start else ""
        if start and not inst:
            inst = self._ask_install(game)
            if not inst:
                return
        try:
            exe, args, ver, plat = LA.game_exe(game, inst) if start else ("", [], "", "")
            LA.write_load_file(game, LA.data_dir_of(md), keys, os.path.join(WORK_DIR, "backups"))
        except LA.LauncherError as e:
            messagebox.showwarning(APP_NAME, str(e), parent=self)
            return
        if not start:
            self.toast(f"The game will load \"{ps.name}\" ({len(keys)} mods) next time it starts.")
            return
        extra = (["-continuelastsave"] if self.cfg.get("play_continue") else []) + \
                (["-debug_mode"] if self.cfg.get("play_debug") else [])
        try:
            proc = LA.start_game(exe, args, extra, appid=LA.game_info(game).get("appid", ""))
        except LA.LauncherError as e:
            messagebox.showwarning(APP_NAME, str(e), parent=self)
            return
        self.toast(f"Starting {game} with \"{ps.name}\" ({len(keys)} mods).")

        def watch():
            t0 = time.time()
            try:
                proc.wait(timeout=20)
            except Exception:
                return                                # still running after 20 s: it started fine
            if LA.proton_copy(exe):
                return                                # Steam started it; its own process ends at once
            if time.time() - t0 < 20 and plat == "steam" and not LA.running("steam.exe"):
                self.q.put(("play_failed", "The game closed right away. Steam isn't running, and Steam copies "
                                           "of the game need it."))
        threading.Thread(target=watch, daemon=True).start()

    # ================================================================ downloads
    def start_run(self):
        """The Catch tab's Start: everything on the catch list (plus unfinished downloads, if you want them).
        Links still in the box go to the list first; they download with the next Start."""
        typed = self.catch.ids()
        if typed:
            self.catch.to_list()
            self.toast(f"{len(typed)} link{'s' if len(typed) != 1 else ''} from the box went to the catch list "
                       "first: press Start again (or Download all) to download them.", color=ACCENT)
            return
        ids = [i for i in self.catch_list if not self.list_state(i)[0].startswith("↓") and i not in self.dep_check]
        if self.pending and not ids:
            return self.resume_run()
        if not ids:
            messagebox.showwarning(APP_NAME, "The catch list is empty. Paste Workshop links (mods or collections) "
                                             "in the box, or find mods in the Browse tab.", parent=self)
            return
        if not self.mod_dir():
            if not messagebox.askyesno(APP_NAME, "No game chosen at the top. Save the mods to the downloads "
                                                 "folder instead?", parent=self):
                return
        self.catch_ids(ids)

    def _pending_count(self):
        if not self.pending:
            return 0
        return sum(1 for it in self.pending["items"] if not it.is_collection and it.state in E.RESUMABLE)

    def resume_run(self):
        q = self.pending or E.load_queue(os.path.join(WORK_DIR, "queue.json"))
        if not q:
            self.catch.set_running(False, False)
            return
        self.pending = None
        if q.get("replace"):
            self.update_run = dict(q["replace"])
        self._launch([], resume=q)

    def pause_run(self):
        if self.engine:
            self.engine.request_stop(pause=True)
            self.log("Pausing: what's downloaded so far is kept...")

    def cancel_run(self):
        if self.engine:
            if messagebox.askyesno(APP_NAME, "Stop and throw away the partial downloads?" +
                                   (f"\n\nThe {len(self.up_next)} mod(s) waiting to start after this run are "
                                    "cancelled too." if self.up_next else ""), parent=self):
                self.up_next = []
                self.engine.request_stop(pause=False)
                self.log("Stopping...")
        elif self.pending or os.path.exists(os.path.join(WORK_DIR, "queue.json")):
            if messagebox.askyesno(APP_NAME, "Throw away the unfinished downloads?", parent=self):
                E.discard_queue(WORK_DIR)
                self.pending = None
                self.banner.hide("resume")
                self.catch.set_running(False, False)
                self._run_status()

    def start_updates(self, jobs):
        """jobs = {workshop id: [old copies to remove once the new version is installed]}"""
        if self.running():
            messagebox.showinfo(APP_NAME, "A download is running. Update once it has finished.", parent=self)
            return
        names = sorted({os.path.basename(o["modfile"]) for olds in jobs.values() for o in olds})
        self.log(f"Updating {len(jobs)} mod(s). Old copies are removed only after the new version is installed: "
                 + ", ".join(names))
        self.update_run = jobs
        self.show_tab("Catch")
        self._launch(list(jobs), {"force_ids": list(jobs), "replace": jobs})

    def _launch(self, ids, extra=None, resume=None):
        cfg = json.loads(json.dumps(self.cfg))
        cfg.update(extra or {})
        cfg["enabled"] = self.effective_enabled()
        if not any(cfg["enabled"].values()):
            messagebox.showwarning(APP_NAME, "Every download site is switched off for this game (Steam is off "
                                             "because you don't own it there). Switch a site on in Settings.",
                                   parent=self)
            return
        cfg["have_ids"] = sorted(self.installed_wids())
        self.catch.clear_queue()
        self.banner.hide("resume")
        self.catch.set_running(True)
        self.library.set_busy(True)
        self.dl_state = {i: ("Queued", None) for i in ids}
        self.run_total, self.run_done = 0, 0
        self.engine = E.Engine(cfg, APP_DIR, lambda *a: self.q.put(a), bridge=self.bridge)
        threading.Thread(target=self.engine.run, args=(ids,), kwargs={"resume": resume}, daemon=True).start()
        self.playsets._buttons_state()
        self._run_status()
        self._refresh_browse_status()

    def _finished(self, s):
        self.engine = None
        self.library.set_busy(False)
        self.banner.hide("check")
        if self.bridge:                                  # the check window never outlives a run
            threading.Thread(target=self.bridge.close, daemon=True).start()
        parts = [f"{n} from {src}" for src, n in s.get("by_source", {}).items()]
        if s.get("installed"):
            parts.append(f"{s['installed']} installed")
        if s.get("saved"):
            parts.append(f"{s['saved']} saved to the downloads folder")
        if s.get("already"):
            parts.append(f"{s['already']} already had")
        if s.get("missing"):
            parts.append(f"{s['missing']} not found (see not_found.txt)")
        if s.get("paused"):
            parts.append(f"{s['paused']} paused")
        if s.get("interrupted"):
            parts.append(f"{s['interrupted']} interrupted")
        head = "Paused" if s.get("paused") else ("Stopped" if s.get("stopped") else
                                                 ("Failed" if s.get("error") else "Finished"))
        self.log(f"{head} in {s.get('seconds', 0)}s: " + (", ".join(parts) or "nothing downloaded"))
        md = self.mod_dir()
        if self.update_run:
            done = set(s.get("done_ids", [])) & set(self.update_run)
            failed = set(self.update_run) - done
            if done:
                U.clear_ids(UPDATES_FILE, md, done)
                for wid in done:                     # playsets follow a mod whose .mod file got a new name
                    for old in self.update_run.get(wid, []):
                        ok = os.path.basename(old.get("modfile", ""))
                        if ok and ok != wid + ".mod" and md:
                            self.profiles.rename_key(md, ok, wid + ".mod")
                self.playsets.loaded_for = None
            if failed and not s.get("resumable"):
                self.log(f"{len(failed)} update(s) could not be downloaded; those mods were left as they were.")
            if not s.get("resumable"):
                self.update_run = None
        if self.cfg.get("add_new_to_playset", True) and md:
            self.to_add = [i + ".mod" for i in s.get("installed_ids", s.get("done_ids", []))
                           if not (self.update_run or {}).get(i)]
        finished_ids = set(s.get("done_ids", [])) | set(s.get("already_ids", []))
        if finished_ids:
            self.catch.remove_ids(finished_ids)
            if finished_ids & set(self.catch_list):        # installed: they leave the catch list
                for wid in finished_ids:
                    self.catch_list.pop(wid, None)
                self.catch_list_changed()
        self.catch.render_list()
        self.catch._retry_button()
        self.pending = E.load_queue(os.path.join(WORK_DIR, "queue.json")) if s.get("resumable") else None
        self.catch.set_running(False, bool(self.pending))
        if self.pending:
            self._resume_banner()
        nxt, self.up_next = self.up_next, []
        if nxt and (s.get("paused") or s.get("stopped") or self.pending):
            self.catch.add_links(nxt)                # not lost: they wait in the links box
            self.log(f"{len(nxt)} mod(s) that were up next are waiting in the links box.")
            nxt = []
        self.playsets._buttons_state()
        self._run_status()
        self.rescan()
        if nxt:
            def go(nxt=nxt):
                jobs = self.update_jobs_for(nxt)
                if jobs:
                    self.update_run = jobs
                    self._launch(nxt, {"force_ids": list(jobs), "replace": jobs})
                else:
                    self._launch(nxt)
            self.after(600, go)
        elif head == "Finished" and (s.get("installed") or s.get("missing")):
            bits = []
            if s.get("installed"):
                bits.append(f"{s['installed']} mod{'s' if s['installed'] != 1 else ''} installed")
            if s.get("missing"):
                bits.append(f"{s['missing']} not found")
            self.toast("Downloads finished: " + ", ".join(bits) + ".", color=WARN if s.get("missing") else OK)

    def _resume_banner(self):
        n = self._pending_count()
        self.banner.show(f"{n} download{'s' if n != 1 else ''} waiting. Resume continues each one where "
                         "it stopped.", actions=[("Resume", self.resume_run), ("Discard", self.cancel_run)],
                         kind="resume")

    def _refresh_browse_status(self):
        self._browse_dirty_status = True

    # ================================================================ event loop
    def _drain(self):
        try:
            self._drain_events()
        except Exception:
            self._report(traceback.format_exc())
        finally:
            self.after(120, self._drain)

    def _drain_events(self):
        latest = {}
        changed_dl = False

        def flush():
            nonlocal changed_dl
            for iid, st in latest.items():
                self.catch.set_status(iid, *st)
                self.dl_state[iid] = (st[0], st[2])
                changed_dl = True
            latest.clear()
        handlers = {
            "add": lambda it: self.catch.add_item(it),
            "log": lambda msg: self.log(msg),
            "progress": self._progress,
            "bridge": self._bridge_event,
            "scan": self._scanned,
            "updates": lambda *a: (self.library.show_updates(*a), self._tab_info()),
            "analysis": self._analysis_done,
            "an_progress": self._an_progress,
            "thumbs": lambda: self._thumbs_ready(),
            "ws_page": lambda *a: self.browse.page_loaded(*a),
            "ws_thumb": lambda *a: self.browse.thumb_ready(*a),
            "ws_details": lambda *a: self.browse.details_loaded(*a),
            "ws_card": lambda *a: self.browse.card_ready(*a),
            "play_failed": lambda msg: self.banner.show(f"{WARN_ICON}  {msg}", actions=[("Start Steam", LA.start_steam)],
                                                        kind="play"),
            "finished": self._finished,
            "deps": self._deps_found,
            "links_resolved": self._links_resolved,
            "compat": lambda *a: self.conflicts.compat_found(*a),
            "storage": self._storage_measured,
            "storage_cleared": self._storage_cleared,
        }
        for _ in range(3000):
            try:
                ev, *a = self.q.get_nowait()
            except queue.Empty:
                break
            if ev == "status":
                latest[a[0]] = a[1:]
                continue
            flush()
            h = handlers.get(ev)
            if h is None:
                continue
            try:
                h(*a)
            except Exception as e:
                self._report(traceback.format_exc(), e)
        flush()
        if changed_dl and self.catch_list:
            self.catch.refresh_list()
        if (changed_dl or self._browse_dirty_status) and self.visible("Browse"):
            self._browse_dirty_status = False
            self.browse.refresh_status()

    def _progress(self, done, total):
        self.catch.set_progress(done, total)
        self.run_done, self.run_total = done, total
        self._run_status()

    def _an_progress(self, token, txt):
        if token == self.an_token:
            self.an_progress = txt
            self._tab_info()

    def _bridge_event(self, e):
        if e.get("event") == "verify_needed":
            what = "this download" if e.get("kind") == "file" else "its pages"
            self.banner.show(f"{WARN_ICON}  {e.get('host')} wants a human check for {what}. Tick "
                             "'Verify you are human' in the 'Site check' window to continue.", kind="check")
        elif e.get("event") == "verified":
            self.banner.hide("check")
            self.log(f"{e.get('host')}: check passed, continuing.")

    # ================================================================ startup / settings / theme
    def _welcomed(self):
        self._fill_games()
        self._fill_versions()
        self.catch.draw_chain_strip()
        self.browse.game_changed()
        self._need = None
        try:
            self.splash.deiconify()
        except tk.TclError:
            pass
        self.after(30, self._boot)
        self.after(4000, self._open_help_first)

    # ---- the loading screen's work, in steps (each step returns to the event loop so it stays responsive)
    def _boot(self):
        self._boot_t0 = time.time()
        self.ask_steam_owned(self.game())
        self.splash.step("Reading your mods...", 0.25)
        self.rescan()
        self._boot_wait(lambda: self.mods_loaded, 30, self._boot_analysis)

    def _boot_wait(self, ready, limit, then, every=80):
        t0 = time.time()

        def check():
            if ready() or time.time() - t0 > limit:
                then()
            else:
                self.after(every, check)
        check()

    def _boot_analysis(self):
        self.splash.step(f"Checking your {len(self.mods)} mods...", 0.35)

        def ready():
            if self.an_progress:
                self.splash.step(f"Checking your mods: {self.an_progress}...", 0.35 + 0.3 * min(1, (time.time() - t0) / 30))
            return not self.analyzing
        t0 = time.time()
        self._boot_wait(ready, 45 if self.mods else 1, self._boot_pictures, every=150)

    def _boot_pictures(self):
        self.splash.step("Preparing pictures...", 0.68)
        mods = list(self.mods)
        H = px(32)
        done = {"n": False}

        def work():
            try:
                for m in mods:
                    path = self.thumb(m)
                    if path:
                        icons.load_thumb(path, H)
            finally:
                done["n"] = True
        threading.Thread(target=work, daemon=True).start()
        self._boot_wait(lambda: done["n"], 15, self._boot_workshop)

    def _boot_workshop(self):
        if self.cfg.get("tab", "Browse") == "Browse" and self.browse.appid():
            self.splash.step("Opening the Workshop...", 0.78)
            self.browse.first_visit()
            self._boot_wait(lambda: not self.browse.loading, 8, self._boot_draw)
        else:
            self._boot_draw()

    def _boot_draw(self):
        self.splash.step("Drawing your lists...", 0.88)
        self._prerender = True
        try:
            for page in (self.library, self.playsets, self.conflicts, self.browse):
                if hasattr(page, "on_show"):
                    page.dirty = True
                    page.on_show() if page is not self.browse else page.render()
                self.update_idletasks()
        finally:
            self._prerender = False
        self.splash.step("Ready", 1.0)
        self.after(120, self._boot_done)

    def _boot_done(self):
        try:
            self.splash.destroy()
        except tk.TclError:
            pass
        self.deiconify()
        self.show_tab(self.cfg.get("tab", "Browse"))
        self.lift()
        self.focus_force()
        self.log(f"Ready in {time.time() - self._boot_t0:.1f}s.")
        self.pending = E.load_queue(os.path.join(WORK_DIR, "queue.json"))
        if self.pending:
            for it in self.pending["items"]:
                self.catch.add_item(it)
                self.catch.set_status(it.id, "Paused" if it.state in E.RESUMABLE else it.state, "", None)
            self.catch.set_running(False, True)
            self._resume_banner()
        self._run_status()
        self._tab_info()
        self.after(2500, self.check_storage)
        self.after(3500, self._crash_banner)
        if self.cfg.get("seen_version") != APP_VERSION:
            if not self._first_run:
                self.after(1200, lambda: WhatsNewWindow(self))
            self.cfg["seen_version"] = APP_VERSION
            self.save()

    # ---- cached files that only take up room
    def check_storage(self, on_done=None):
        """Measure the cached pictures and pages (in the background); above the limit, offer to clear them."""
        busy = self.running() or bool(self.pending)

        def work():
            cats = ST.categories(WORK_DIR, busy)
            self.q.put(("storage", cats, on_done))
        threading.Thread(target=work, daemon=True).start()

    def _storage_measured(self, cats, on_done=None):
        if on_done:
            on_done(cats)
            return
        total = ST.total(cats)
        limit = int(self.cfg.get("cleanup_limit_mb", ST.DEFAULT_LIMIT_MB)) * 1000 * 1000
        if total <= limit:
            return
        if self.banner.kind is not None:          # something more important is showing: ask a bit later
            self.after(60000, self.check_storage)
            return
        self.banner.show(f"Cached pictures and pages take {ST.human(total)} (your limit is "
                         f"{ST.label_mb(int(self.cfg.get('cleanup_limit_mb', ST.DEFAULT_LIMIT_MB)))}). They come back "
                         "by themselves when needed. Clear them?",
                         actions=[("Clear them", lambda: self.clear_storage(cats)),
                                  ("Change the limit", lambda: self._open_settings("Storage")),
                                  ("Not now", lambda: self.banner.hide("storage"))], kind="storage", tone="info")

    def clear_storage(self, cats, on_done=None):
        self.banner.hide("storage")

        def work():
            freed = ST.clear(cats)
            self.q.put(("storage_cleared", freed, on_done))
        threading.Thread(target=work, daemon=True).start()

    def _storage_cleared(self, freed, on_done=None):
        self._thumbs.clear()
        self.toast(f"Freed {ST.human(freed)} of cached files.")
        if on_done:
            on_done(freed)

    def _open_help_first(self):
        self.toast("Tip: ? (top right) explains every part of the app, starting with \"Start here\".", color=ACCENT)

    def _theme_label(self):
        dark = ctk.get_appearance_mode() == "Dark"
        self.theme_btn.configure(image=icon("sun" if dark else "moon", 15))

    def offer_restart(self):
        """The palette changed: it applies when the app starts again."""
        new = self.cfg.get("palette", "Classic")
        if self.engine:
            messagebox.showinfo(APP_NAME, f"The {new} palette applies the next time the app starts (downloads are "
                                          "running, so it doesn't restart now).", parent=self)
            return
        if messagebox.askyesno(APP_NAME, f"The {new} palette applies when the app starts again.\n\nRestart now?",
                               parent=self):
            self.restart()

    def restart(self):
        args = [sys.executable] + (sys.argv[1:] if getattr(sys, "frozen", False) else
                                   [os.path.abspath(sys.argv[0])] + sys.argv[1:])
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            # A one-file .exe started from itself would reuse this copy's unpack folder in %TEMP%, which
            # is deleted when this copy closes (the new one then can't find its files and crashes).
            # Tell PyInstaller to start fresh, and drop what this copy passed on.
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            for k in list(env):
                if k.startswith("_PYI_") or k in ("_MEIPASS2", "_PYI_SPLASH_IPC"):
                    env.pop(k, None)
        self._close()                       # saves everything; no downloads run (offer_restart checked)
        try:
            subprocess.Popen(args, cwd=APP_DIR, close_fds=True, env=env)
        except Exception as e:
            print("restart failed:", e)

    def _toggle_theme(self):
        new = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        self.cfg["theme"] = new
        self.save()
        ctk.set_appearance_mode(new)
        self._restyle()

    def _open_help(self):
        if self.help_win and self.help_win.winfo_exists():
            self.help_win.focus()
            return
        tab = self.tabs.get() or ""
        topic = next((t for t, _ in HT.TOPICS if t.split(":")[0].strip() == tab), None)
        self.help_win = HelpWindow(self, topic)

    def _open_settings(self, tab=None):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.focus()
            if tab:
                self.settings_win.tabs.set(tab)
            return
        self.settings_win = SettingsWindow(self, tab)

    def apply_settings(self, cfg):
        for k in NOT_IN_SETTINGS_WINDOW:
            cfg[k] = self.cfg.get(k, DEFAULTS[k])
        hints_changed = cfg.get("workshop_hints") != self.cfg.get("workshop_hints")
        older_changed = cfg.get("older_first") != self.cfg.get("older_first")
        dirs_changed = cfg.get("game_dirs") != self.cfg.get("game_dirs")
        self.cfg = cfg
        self.save()
        ctk.set_appearance_mode(cfg.get("theme", "System"))
        self._restyle()
        self.catch.draw_chain_strip()
        self.catch.update_workers_warn()
        if dirs_changed:
            self._installs.clear()
            self._fill_versions()
        if hints_changed or dirs_changed:
            self.schedule_analysis(force=True)
        elif older_changed:
            self.playsets.refresh_derived()
        en = self.effective_enabled()
        self.log("Settings saved. Chain: " + "  >  ".join(
            S.SOURCE_BY_KEY[k].name for k in cfg["order"] if en.get(k)))
        if self.running():
            self.log("The running downloads keep the old settings; the next run uses the new ones.")

    def _close(self):
        if self.engine:
            ans = messagebox.askyesnocancel(APP_NAME, "Downloads are running. Pause them and continue next time?\n\n"
                                                      "No stops them and throws partial downloads away.", parent=self)
            if ans is None:
                return
            self.engine.request_stop(pause=bool(ans))
            t0 = time.time()
            while self.engine and time.time() - t0 < 8:      # let the engine save its queue
                self.update()
                try:
                    ev, *a = self.q.get(timeout=0.1)
                    if ev == "finished":
                        break
                except queue.Empty:
                    pass
        try:
            if self.state() == "normal":
                self.cfg["geometry"] = self.geometry()
        except Exception:
            pass
        if self.up_next:
            self.catch.add_links(self.up_next)
        self.cfg["catch_links"] = self.catch.links_text()
        self.save()
        if self.bridge:
            threading.Thread(target=self.bridge.close, daemon=True).start()
        self.destroy()


if __name__ == "__main__":
    multiprocessing.freeze_support()          # the check window runs as a second copy of the .exe
    if sys.platform.startswith("win"):
        try:                                  # the taskbar shows our icon (not Python's) and groups our windows
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Adromedary.ParadoxicalLauncher")
        except Exception:
            pass
    App().mainloop()
