# Changelog

## 1.0.1

* Fixed: in Browse's panel view the last row of cards couldn't be scrolled to.
* Fixed: the end of long Help topics could be cut off the same way.

## 1.0

First public release, as **Adromedary's Paradoxical Launcher** (formerly Paradox Mod Catcher).

* **Browse**: the game's Steam Workshop inside the app, with list and panel views, categories,
  game-version fit, required mods, screenshots, live download status per mod and a catch list.
* **Catch**: a chain of seven download sites, parallel downloads, pause / resume across restarts,
  mods caught during a run start right after it, finished links leave the links box.
* **Library**: role badges, pictures, shared files, version notes, Workshop updates, bulk actions.
* **Playsets**: load order editing with undo / redo, rules, Auto-sort with a reasoned preview,
  import / export to the Paradox launcher.
* **Conflicts**: every problem in the active playset by severity, explained, with a compatch search.
* **Play**: starts the game with the playset directly.
* First start asks which game you play and whether you own it on Steam (Steam is skipped otherwise).
* Resizable panels everywhere (remembered), lists that hide minor columns on narrow windows, a header
  that folds to fit, drawn icons, light / dark / system themes.
* Fixed: on a first run, a mod could be saved to the downloads folder instead of being installed
  when Steam's store didn't answer the game-name lookup; mods are now matched by Steam app ID.
* Fixed: freshly installed mods weren't always shown as installed in Browse.
* Unexpected errors are logged to `.work\errors.log` and no longer stop the app's event loop.
* A loading screen prepares everything once at start; the mod analysis is cached on disk, so later
  starts take a couple of seconds.
* Faster everywhere: detail panels update in place instead of being rebuilt, panel-view cards are
  single pictures drawn in the background, hidden tabs draw only when opened.
* Correct at Windows display scales above 100 % (tested at 125 and 150 %): category chips, detail pictures and text no
  longer overflow, and a customtkinter scrollbar redraw loop at fractional scales is guarded against.
* Panels keep the normal mouse cursor (the dividers' resize cursor no longer sticks).
* Tab counters drawn inside the tabs; tinted pills, banners and summary tiles; striped lists; hover
  tips on icon buttons; square picture cards in Browse.
