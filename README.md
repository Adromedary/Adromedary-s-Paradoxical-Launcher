<<<<<<< HEAD
# Adromedary's Paradoxical Launcher

*Version 1.0 · by Adromedary*

A mod manager and launcher for Paradox games: **Crusader Kings III**, **Europa Universalis IV / V**,
**Stellaris**, **Hearts of Iron IV**, **Victoria 3** and **Imperator: Rome**.

Browse the Steam Workshop inside the app, download mods (even without owning the game on Steam),
see which ones clash and why, sort them into a working load order, and start the game with them.
No Paradox launcher needed.

![Browse, panel view](docs/screenshots/browse-panels.png)

## What it does

| Tab | |
|---|---|
| **Browse** | Your game's Steam Workshop: search, sort (trending, popular, top rated, newest, recently updated), category filters (must have / hide), game-version fit, mods or collections. A list or big picture panels. Each mod shows its pictures, description, the mods it needs and whether you already have it. Catch one with a double-click; it downloads while you keep browsing. |
| **Catch** | Downloads mods and whole collections through a chain of sites (Steam, SkyMods, mod.io, Thunderstore, ModDB, GitHub, steamworkshop.download) and installs them into the game's mod folder. Pause and resume, even across restarts. Mods caught during a run start right after it. |
| **Library** | Every installed mod with its picture, a role badge (fix pack, overhaul, map, events, interface... 20 kinds), shared files, version notes and Workshop updates. |
| **Playsets** | Named mod lists in load order. Drag to reorder, undo / redo, your own "load after" rules, and **Auto-sort**, which works out the best order from the mods' files, what they use from each other and their Workshop pages. |
| **Conflicts** | Everything that can go wrong in the active playset, from "these don't work together" to harmless, each explained with what happens in game and what to do. |
| **Play** | Writes the playset into the game's load file and starts the game the way the Paradox launcher does. |

| | |
|---|---|
| ![Library](docs/screenshots/library.png) | ![Playsets, dark theme](docs/screenshots/playsets-dark.png) |
| ![Conflicts](docs/screenshots/conflicts.png) | ![Browse, list view](docs/screenshots/browse-list.png) |

## Getting started

1. Download `ParadoxicalLauncher.exe` from the Releases page (or build it, see below) and put it in
   a folder of its own. It keeps its settings and downloads next to itself.
2. Start it. It asks two things: which game you play, and whether you own it on Steam. (Steam only
   hands out Workshop files to owners; if you don't own the game there, Steam is skipped and the
   other sites are used.)
3. Find mods in **Browse**, press **Catch now**, sort them in **Playsets**, check **Conflicts**,
   press **Play**.

The **?** button explains every part of the app, starting with a step-by-step "Start here".
Buttons that only show an icon explain themselves when you rest the pointer on them.

A short loading screen opens the app: it reads your mods, checks them, prepares their pictures and
draws every list, so the window opens ready to use. The check is kept on disk: while your mods don't
change, later starts take a couple of seconds.

![First start](docs/screenshots/welcome.png)

## How it works

### Downloading
Each mod is tried on every enabled site in order until one delivers it:

| # | Site | How it finds the mod |
|---|------|----------------------|
| 1 | **Steam** (SteamCMD) | The official source. Paradox games only serve Workshop files to accounts that own the game. Skipped for games you don't own there. |
| 2 | **SkyMods** | Exact Workshop ID. |
| 3 | **mod.io** | Game and mod name. Needs a free API key. |
| 4 | **Thunderstore** | Game and mod name. |
| 5 | **ModDB** | Game and mod name, newest file. |
| 6 | **GitHub Releases** | Repository name plus game. |
| 7 | **steamworkshop.download** | Exact Workshop ID; only copies it cached earlier. |

Settings switches sites off or reorders them. Mods are matched to the game by Steam's app ID, and
installed as `mod\<id>\` plus `mod\<id>.mod`, whatever shape the download came in. Mods that are
already there (also copies Steam installed) are skipped. Partial downloads resume with HTTP range
requests; the queue survives closing the app.

SkyMods' file host shows a Cloudflare "verify you are human" check on downloads. With the check
window on, the page opens in a small browser window: if the check passes by itself nothing is shown,
otherwise the window appears and **you** tick the box. The app never ticks it for you.

### Analysis
After each scan every mod is read once in the background and compared with the game's own files
(when the install folder is known): which files it overrides and how much it changes in each, which
names it defines and uses, its texts, events and on-actions. From that come:

* **Roles**: what kind of mod it is, from what its files actually do.
* **Conflicts**, by severity: critical (declared incompatible, two total conversions, a missing
  dependency, the same mod twice), high (duplicate event IDs, overwritten on-action effects, the same
  new name used for different things, two mods replacing one window), medium (both change the same
  objects in differently named files: only a compatch keeps both), low and info.
* **Auto-sort**: a weighted ordering of your rules, declared dependencies, compatch / add-on names,
  "load after X" notes on Workshop pages, merged files, mods building on others, and the real cost of
  each shared-file clash. Mods that share nothing keep your order. You see a preview with the reason
  for every move before anything changes.

### Play
The playset's mods go, in order, into `Documents\Paradox Interactive\<game>\dlc_load.json`
(`content_load.json` for Victoria 3 and EU V), DLC settings untouched, with a backup in
`.work\backups`. The game is started with the arguments from its `launcher-settings.json`. The
install folder is found through Steam and GOG, or set in Settings > Games.

## Files next to the app

| | |
|---|---|
| `settings.json` | your choices |
| `profiles.json` | your playsets |
| `installed.json` | what was installed from where |
| `updates.json` | the last update check |
| `not_found.txt` | mods no site had, with each site's reason |
| `steamcmd\` | Valve's downloader |
| `.work\` | the resume queue and partial downloads, backups, cached Workshop pages and pictures, the game's definitions (once per version), `errors.log` |

## Build

Windows, Python 3.10 or newer ("Add python.exe to PATH" ticked). Double-click **`build.bat`**.
The result is `dist\ParadoxicalLauncher.exe`.

## Run from source

    pip install -r requirements.txt
    pip install pywebview            (optional: the "verify you are human" window)
    python paradoxical_launcher.py

## Code map

| File | |
|---|---|
| `paradoxical_launcher.py` | main window, settings, help, welcome, event loop |
| `gui_browse.py`, `gui_catch.py`, `gui_library.py`, `gui_playsets.py`, `gui_conflicts.py` | the tabs |
| `gui_common.py`, `glyphs.py`, `icons.py`, `cards.py`, `appicon.py` | look: colours, shared widgets (tabs, detail panels, dividers, tips), drawn icons, pictures, Browse cards, app icon |
| `workshop.py` | reading the Steam Workshop (browse pages, item details) |
| `engine.py`, `sources.py`, `net.py`, `installer.py`, `browser_helper.py` | downloading and installing |
| `modscan.py`, `script.py`, `analysis.py`, `roles.py`, `loadorder.py` | reading mods, conflicts, roles, Auto-sort |
| `launcher.py`, `profiles.py`, `updates.py`, `versions.py` | games, playsets, updates, versions |
| `help_text.py` | the Help window's text |

## Notes

* SkyMods and steamworkshop.download re-host Workshop content without the creators' involvement;
  using them may conflict with Steam's terms. They can be switched off in Settings.
* Nexus Mods can't be automated (it blocks automated access; its download API needs Premium).
* If Steam changes its Workshop page, Browse may stop working until the app is updated; Catch keeps
  working with links.
=======
## Adromedary's Paradoxical Launcher

A mod manager and launcher for Crusader Kings III, Europa Universalis IV,
Stellaris, Hearts of Iron IV, and Imperator: Rome.

### Highlights
- **Browse** the game's Steam Workshop inside the app: search, categories, game-version fit,
  required mods, screenshots, list or picture-panel view.
- **Catch** mods and whole collections; downloads run in parallel and resume after restarts.
- **Library** shows every installed mod with a role badge (overhaul, map, fix pack, interface...),
  shared files, version notes and Workshop updates.
- **Playsets** with drag-and-drop load order, undo / redo, your own rules and **Auto-sort**,
  which explains every move before applying it.
- **Conflicts** lists everything that can go wrong in a playset, by severity, in plain words,
  with what happens in game and what to do.
- **Play** starts the game with your playset directly. No Paradox launcher needed.
- Light / dark themes, remembered panel sizes, works at Windows display scaling up to 150 %.

### Install
1. Download `ParadoxicalLauncher.exe` below and put it in a folder of its own
   (it keeps its settings next to itself).
2. Run it. It asks which game you play and whether you own it on Steam.

### Notes
- The exe isn't code-signed, so Windows SmartScreen may show "Windows protected your PC".
  Click **More info → Run anyway**. Some antivirus programs flag PyInstaller apps by mistake;
  the full source is here if you'd rather build it yourself (`build.bat`).
- Your playsets and the game's `dlc_load.json` are backed up before anything is written.
>>>>>>> 06ed745328e604da6950aac236ed1407fc7766e0
