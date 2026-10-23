# Changelog

## 2.0 (2026-10-19)

The biggest update so far: conflicts you can act on, a smarter Auto-sort, playset rules, a new Crashes
tab, redesigned Settings and a Colorful palette. The app shows a "What's new" window once after updating.

### Conflicts
* Each conflict says what you'll notice in game, what solves it (load order, a compatch, turning one
  off...) and how sure the app is (certain, likely, possible).
* New checks: two mods setting the same game value (defines), the same interface template or type
  (the first file wins there), and a mod's copy of a game file leaving out things another mod uses.
  Conflicts over shared files list the exact objects each side loses.
* Compatches you have are recognised: their conflicts become harmless, Auto-sort loads them after
  both mods, and an installed compatch that's turned off is offered to you.
* Look for a compatch: searches the Workshop for a patch for the two mods, saying how sure it is and
  whether it may be outdated.
* Save compatch report: a Markdown file with everything needed to make a compatch, the objects both
  mods change side by side with the game's own, and a ready prompt for an AI chat.
* Conflicts you accept can be hidden (and shown again, also all at once from Settings > Sorting).

### Auto-sort 2 and Playsets
* Auto-sort loads recognised compatches after both mods they patch, keeps fix packs and total
  conversions near the top and puts interface mods near the bottom.
* The preview says how sure each move is (certain, likely, possible, or just convention) and counts
  them at the top.
* New option "Mods for older game versions load first" (in the preview and Settings > Sorting), so
  newer mods win the files they share. Off by default.
* Your rules at the top of a mod's details: Placement (First, Early, Late, Last in the whole list)
  plus "loads after / before" another mod. Auto-sort keeps First, Last and before / after, and
  follows Early / Late.
* The details panel has Turn off, Remove, Open folder and Delete.
* Clear rules: the broom next to Auto-sort clears the selected mods' rules (also in the right-click
  menu); Clear all rules, with the playset buttons, removes every rule of the playset after asking.
* The enabled list's column headings (Role, Shared files, Issues) resize the way you drag them.

### Library
* A playset menu on the search row shows one playset's mods (yours, with the one Play starts marked,
  or the official Paradox launcher's), and Sort > Enabled first lists the mods turned on first.
* Role recognition rewritten: clues are weighed together (what the files change, what they prove, the
  title, the Workshop description and the author's categories, which count less the more of them a
  mod ticks). "Total conversion" needs proof in the files, so mods like Congenital Beauty, which tick
  it themselves, are no longer called one (or reported as two clashing total conversions). Each mod's
  details say why it got its role, and you can set a role yourself (Automatic goes back).

### Browse and Catch
* Searches show the best matches first (title, then author, then description), and a refresh button.
* Every screenshot of a mod (only the first one showed before), and a picture viewer inside the app
  (click the big picture or a screenshot; arrow keys step through them).
* Mods that need other Workshop mods: you're asked whether to catch those too (missing ones, and ones
  you have in an older version). Settings > General turns the question off.
* The catch list is kept between sessions and shown in full in the Catch tab: download or remove each
  mod, Download all, Clear all. A mod leaves it only when it's installed or you remove it.
* Downloads that didn't work can be retried one by one or all at once.
* Pasted Workshop links (mods or collections) go on the catch list instead of downloading at once; a
  collection is opened up into its mods there, with their names. Start downloads the catch list.
* Library's "Update all" is now **Catch All**: every mod with an update goes on the catch list.
* A caught mod that's installed but has a newer version is updated (the old copy replaced once the
  new one is in) instead of being skipped as already there.

### Crashes (new tab)
* After a crash, the tab says what the game was doing (loading, setting up a new game, playing...) and
  what failed, in plain words, and names the mods most likely to blame: Likely, Possible or Unlikely,
  each with its evidence.
* The evidence comes from the session's error log: every error is traced to the mod whose file it
  points at (the copy the game loaded) and weighed by kind. Files that don't load and broken events
  count most; things a mod uses that this game version doesn't have come next, with renames explained
  from the game's own tables ("scholar" is "erudite" in 1.20). When a mod's copy of a game file leaves
  out something others use, the blame goes to it. The last errors before the crash count more; the
  playset's conflicts, missing required mods and mods for older versions add to it.
* Find the culprit: a copy of your playset ("Crash test") with about half of the suspects off (the
  likeliest first, with the mods that need them); you play and answer, and a few rounds later one mod
  is left. Your playset is never changed unless you turn the culprit off.
* Save crash report: Markdown with everything found and a prompt for an AI chat.
* Last session's errors: the same reading for a game that didn't crash.
* A bar at start and a counter on the tab when there's a crash you haven't looked at; suspects are
  marked in Library, Playsets and Conflicts with a link to the crash; a suspect's conflicts lead to
  Look for a compatch and Save compatch report.
* Open or delete a crash's folder (logs, memory dump and a copy of the save from that moment).
* Crash history: every crash and every game that ended well is remembered with its mods (read from
  the game's log). Mods that were in a game that worked and haven't changed since are cleared; mods
  that never were, that changed after the last good game or just before the crash, or that were in
  every crash at the same stage stand out. Mods you've uninstalled since stay suspects by name.
  Culprit hunt answers are remembered too. Kept in `crash_history.json` next to the app.
* Stronger evidence from the logs: the game's own failed checks ("assertion failed", traced to the
  interface file just before), broken definitions (traits, modifiers, buildings) and interface files
  that don't work; the stage of the crash (start-up, setting up the world, the interface, playing)
  points at the folders the game was using then.

### Everywhere
* Rescan and Check updates moved to the top bar, so they work from every tab.
* Right-click menus in every list: Browse, Catch, Library, Playsets, Conflicts.
* Column dividers move the edge you drag (they used to move the other edge), and the widths you set
  are remembered.
* Cached pictures, screenshots and Workshop pages: above a limit you choose (Settings > Storage,
  100 MB to 10 GB, 250 MB by default) the app offers to clear them at start.
* Settings redesigned: General, Games, Sorting, Download sites, Accounts, Storage, Appearance, About.
* Every search box has an x at its end to clear it at once.
* Help: the topic list scrolls when the window is small.
* New Colorful palette (Settings > Appearance): warm parchment and royal tones, every tab in its own
  colour, and a heraldic ribbon under the top bar. Works in light and dark; applies after a restart,
  which the app offers.
* Help rewritten for 2.0, with new topics (What's new, Crashes) and a "What's new" window.
* A new app icon: Adromedary's crest, on the .exe, the taskbar, every window and inside the app.
* The loading screen sits exactly in the middle of the screen (at any display scale) on a rounded,
  paper-like sheet.

### Fixes
* The conflict check's results are re-done once after updating (the saved check from 1.x can't be
  reused).
* Version strings like `1.20*` (no dot before the star) are read correctly.
* Restarting the app from itself (after changing the palette) no longer crashes the new copy of the
  .exe with "The .json theme file for CustomTkinter could not be found".

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
