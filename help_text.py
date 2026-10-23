"""The Help window's text, written for someone opening the app for the first time.

Each topic is (title, [blocks]); a block is ("p", text), ("h", heading), ("steps", [..]),
("bullets", [..]), ("tip", text) or ("roles", None).
"""
import roles as R

TOPICS = [
    ("Start here", [
        ("p", "Adromedary's Paradoxical Launcher finds mods for Paradox games (Crusader Kings III, Europa "
              "Universalis IV and V, Stellaris, Hearts of Iron IV, Victoria 3, Imperator), downloads them, puts "
              "them where the game expects them, checks which ones clash, sorts them into a good load order and "
              "starts the game with them. You don't need the Paradox launcher, and you don't need to own the game "
              "on Steam to download mods: other sites are used when Steam can't help."),
        ("h", "Your first time, step by step"),
        ("steps", [
            "The first time the app opens it asks two things: which game you play, and whether you own it on "
            "Steam. Steam only gives Workshop mods to owners; if you don't own the game there, Steam is skipped "
            "and the other sites are used.",
            "Open Browse and look for mods: search, sort by what's popular, filter by category, switch between a "
            "list and big picture panels. Or paste Steam Workshop links into Catch if you already have them: they go "
            "on the catch list, and Start downloads it.",
            "Press Catch now on a mod (or double-click it). It downloads and installs by itself while you keep "
            "browsing; its row shows the progress and then ✓ Installed.",
            "Open Playsets. Your mods are listed in the order the game loads them. Tick the ones you want, then "
            "press Auto-sort to put them in a good order.",
            "Look at Conflicts. It tells you, in plain words, if some of your mods don't get along, what "
            "you'll notice in game and what solves it.",
            "Press Play at the top. The game starts with exactly those mods.",
        ]),
        ("tip", "Mods are installed into Documents\\Paradox Interactive\\<game>\\mod, the same place the "
                "official launcher uses. The game's own files are never changed."),
        ("tip", "Every list has a detail panel on its right. Drag the gap between them to make either one wider; "
                "the app remembers it. In Playsets, the gap above \"Not in this playset\" can be dragged too."),
        ("tip", "When the app starts, a short loading screen reads your mods, checks them and draws every list, so "
                "everything is ready when the window opens. The check is remembered: as long as your mods don't "
                "change, the next start takes a few seconds."),
        ("tip", "Rest the pointer on a button without text (arrows, undo, the moon, ?) to see what it does, "
                "and right-click almost anything in a list for what you can do with it."),
    ]),
    ("What's new in 2.0", [
        ("p", "2.0 is the biggest update so far. The short version (Settings > About > What's new shows it with "
              "more detail):"),
        ("bullets", [
            "Conflicts explain what you'll notice in game, what solves it and how sure the app is; compatches "
            "you have are recognised, others can be searched for on the Workshop, and a compatch report (with "
            "a ready prompt for an AI chat) helps you make one.",
            "Auto-sort says how sure it is of each move, places compatches after both mods they patch, and can "
            "load mods for older game versions first.",
            "Playsets have rules (First, Early, Late, Last, before / after a mod) and quick buttons; Library "
            "filters by playset and shows why each mod got its role (which you can change).",
            "Browse ranks searches by best match, shows every screenshot in an in-app viewer and asks about "
            "the mods a mod needs. Catch keeps your catch list and retries failed downloads.",
            "Rescan and Check updates moved to the top bar; right-click menus everywhere; list columns resize "
            "the right way and are remembered.",
            "A Crashes tab: after a crash it names the mods most likely to blame, with the evidence, and finds the "
            "culprit step by step when the logs can't tell. Also a Storage limit for cached files, redesigned "
            "Settings and a new Colorful palette.",
        ]),
    ]),
    ("The top bar", [
        ("bullets", [
            "Game: which game you're working on. Every Paradox game found on this PC is listed; \"Other mod "
            "folder...\" lets you pick any folder.",
            "Version: the version of the game you play. It's read from the game when its install folder is "
            "known. Mods made for another version get a quiet ○ note (they usually still work).",
            "Playset: the list of mods Play starts the game with.",
            "Play: starts the game with that playset. The small arrow next to it: continue your last save, debug "
            "mode, only set the mod list without starting, open the game or mod folder, or the game's error log.",
            "Rescan (the folder with a magnifier) reads the mod folder again; Check updates (the round arrow) "
            "asks Steam which of your mods changed. Both work from every tab and grey out while busy.",
            "The moon / sun button switches dark and light (with either palette), ? opens this help on the page "
            "for the tab you're on, Settings holds the rest.",
            "The tabs: Browse (find mods), Catch (download), Library (what you have), Playsets (what you play "
            "with, in which order), Conflicts (what clashes) and Crashes (why the game crashed). A small number on a tab "
            "counts what needs you: downloads going on, updates waiting, serious conflicts.",
            "Right of the tabs: how far the downloads are. At the bottom of the window: how many mods you have, "
            "your playset's state, and what the app is busy with.",
            "On a narrow window the labels and long names fold away; nothing else changes.",
        ]),
    ]),
    ("Browse: find mods", [
        ("p", "Browse shows your game's Steam Workshop right inside the app, with what you already have "
              "marked. It needs an internet connection but no Steam account."),
        ("h", "Finding things"),
        ("bullets", [
            "Search: type a name, an author or words from the description and press Enter. Best matches come "
            "first: a mod whose title matches beats one that only mentions the words in its description.",
            "The round-arrow button next to Search loads the page again from Steam.",
            "Sort: trending this week / month / year, most popular of all time, top rated, newest, recently "
            "updated.",
            "Mods / Collections: collections are ready-made packs of many mods; catching one catches all of "
            "its mods.",
            "Game version: show everything, only mods marked for your version, or a specific version.",
            "Categories: click one to show only mods that have it (✓), click again to hide mods that have "
            "it (✗), a third time to turn it off. Clear filters resets everything.",
            "Hide mods I have: leaves out what's already installed.",
            "List / Panels (top right): a compact list, or square picture cards in a grid with the version and "
            "what you have of each mod on the card. Both work the same way.",
            "Previous / Next move through the pages (30 mods per page).",
        ]),
        ("h", "Reading it"),
        ("bullets", [
            "Game: ✓ 1.20 = the author marked it for your version; ○ 1.19 = marked for another one; "
            "empty = no version given.",
            "You: ✓ Installed, ↻ Update (a newer version is out than the one you have), ↓ 45% or "
            "↓ Queued (downloading now), ↓ Up next (starts after the current downloads), + In list (in "
            "your catch list), ✗ Not found (no site had it).",
            "Rating shows stars once enough people voted; \"few votes\" until then.",
        ]),
        ("h", "Getting mods"),
        ("bullets", [
            "Double-click a mod, or press Catch now in its details, to download it right away. You stay in "
            "Browse; the Catch tab shows the details.",
            "Catching while other downloads are running puts the mod \"up next\": it starts on its own when they "
            "finish.",
            "To collect several first: select them (Ctrl/Shift-click, in both views) and Add to list. The catch "
            "list (bottom right here, and in full in the Catch tab) is kept until each mod is installed or you "
            "remove it; Download all fetches them.",
            "When a mod needs other Workshop mods you don't have (or have in an older version), you're asked "
            "whether to catch them too. Settings > General turns the question off.",
            "The details show the mod's pictures, its description and the other mods it needs, each marked "
            "✓ if you have it. Click the big picture or a screenshot to see it full size inside the app "
            "(arrow keys or the round buttons step through them).",
            "Right-click a mod for everything you can do with it.",
            "Steam page opens the mod in your web browser; In Library jumps to your copy of it.",
            "In the details, click one of the mod's categories to show only mods of that category.",
        ]),
    ]),
    ("Catch: download", [
        ("p", "Catch downloads mods and installs them. Mods caught in Browse run here. Paste Steam Workshop links "
              "or IDs (mods or collections) into the box and they go on the catch list, nothing downloads yet; "
              "typed links go there with Add to list. Start (or Download all) downloads the catch list."),
        ("bullets", [
            "A pasted collection is opened up into its mods on the catch list, each with its name from Steam.",
            "The chain: each mod is tried on Steam first, then SkyMods, mod.io, Thunderstore, ModDB, GitHub "
            "and steamworkshop.download, until one has it. Steam is left out for games you don't own there. "
            "Settings > Download sites switches sites off or reorders them.",
            "N at a time: how many mods download at once (1 to 5).",
            "Pause keeps what's downloaded so far; Resume continues each file where it stopped, even after "
            "closing the app. Cancel stops and throws partial downloads away.",
            "The queue shows each mod: Queued, Working (with %), Done, Have it (already installed, also when "
            "Steam installed it for you), Not found (no site had it; not_found.txt says why), Paused, Interrupted "
            "(the connection kept dropping; Resume picks it up).",
            "A mod you catch that's already installed but has a newer version is updated (the old copy goes once "
            "the new one is in), not skipped as \"already there\".",
            "Downloads that didn't work show ↻ Retry: click it, or Retry failed above the queue for all of them.",
            "The catch list (right): the mods you added in Browse, from links, or with Catch All in Library. ↓ "
            "downloads one, ✕ removes it; Download all and Clear all work on the whole list. A mod stays listed "
            "until it's installed, and the list is kept when you close the app.",
            "Show log tells you step by step what happened. Mod folder opens it.",
            "Freshly downloaded mods are added to your active playset automatically (Settings > General).",
        ]),
        ("h", "\"Verify you are human\" (SkyMods)"),
        ("p", "SkyMods' file host shows a Cloudflare check on downloads. With the check window on (Settings > "
              "General), the page opens in a small hidden browser window. If the check passes by itself you "
              "see nothing; if it wants a click, the window appears and a yellow bar tells you. Tick the box "
              "yourself (the app never does it for you) and it carries on. Unanswered for 5 minutes, SkyMods "
              "is skipped for that run."),
    ]),
    ("Library: your mods", [
        ("p", "Every mod in the mod folder, with its picture and a role badge saying what kind of mod it is."),
        ("bullets", [
            "Notes column: ⚠ shares files with another mod, ○ made for another game version, "
            "↻ a newer version is on the Workshop, ✗ its folder is missing. Playset column: ✓ on "
            "in the playset shown, \"off\" listed but turned off.",
            "Search, the All / Conflicts / Updates / Version filters, the role filter and Sort narrow the list. "
            "Click a column heading to sort by it. Sort > Enabled first lists the mods turned on in the playset "
            "first (A to Z), then the ones turned off, then the rest.",
            "The playset menu (end of the search row) shows only one playset's mods: All mods, any of your "
            "playsets (▶ and a green dot: the one Play starts) or the official Paradox launcher's playsets, "
            "read from it as they are.",
            "Click a mod for its details: what it is and why (the strongest clues), whether it's "
            "achievement-friendly, possible conflicts with other installed mods, and the exact files it shares "
            "(selectable, Copy paths). \"Change the role...\" (or right-click > Role) sets its role yourself; "
            "Automatic goes back to the app's own reading.",
            "Its buttons: Update (when there is one), Add to playset or In playset, Steam page, Open folder, "
            "Ignore conflicts (leaves it out of the shared-file warnings) and Delete (asks first).",
            "Check updates (the round-arrow button at the top right, on every tab) asks Steam which mods "
            "changed. Update downloads a mod's new version right away; Catch All puts every mod with an update "
            "on the catch list, to download from the Catch tab. The old copy is deleted only after the "
            "new one is installed. Rescan (the folder button next to it) reads the mod folder again.",
            "Right-click a mod for everything you can do with it; drag a column heading's edge to resize it "
            "(remembered).",
            "Ctrl/Shift-click several mods for bulk Update, Delete, Ignore, or adding to / removing from the "
            "active playset.",
        ]),
    ]),
    ("Playsets: what you play with", [
        ("p", "A playset is a list of mods, each turned on or off, in the order the game loads them. You can "
              "keep several (\"Vanilla+\", \"Big overhaul run\"...) and switch with the Playset menu at the top "
              "or the list on the left."),
        ("h", "Load order in one minute"),
        ("p", "The game reads mods from the top of the list to the bottom. When two mods contain the same file, "
              "the one LOWER in the list wins and the other's version of that file is ignored. Mods that "
              "share no files can be in any order. That's all load order is about."),
        ("h", "Using it"),
        ("bullets", [
            "Click the box in the On column to turn a mod on or off (or select it and press Space).",
            "Drag rows to reorder (several at once with Ctrl/Shift), or use the arrow buttons: to the top, up, "
            "down, to the bottom; or Alt+Up/Down. The undo / redo buttons take back any change.",
            "Shared files: how many shared files a mod wins, loses or has merged (its file already includes "
            "the other mod's changes). Issues: its conflicts in this playset.",
            "Click a mod: buttons to turn it off, remove it from the playset, open its folder or delete it; "
            "then your rules for it, its role, its conflicts, why it sits where it does, which files it wins or "
            "loses, and which other mods it uses or is used by.",
            "Your rules (top of the details, or right-click > Placement): Placement puts a mod First, Early, "
            "Late or Last in the whole list; \"+ Loads after...\" / \"+ Loads before...\" ties it to one other "
            "mod. Auto-sort always keeps First, Last and the before / after rules, and follows Early / Late "
            "unless something much stronger says otherwise.",
            "The broom next to Auto-sort clears the rules of the selected mod(s) (right-click > Clear its rules "
            "too); Clear all rules (with the playset buttons on the left) removes every rule of the playset, "
            "after asking. Undo brings rules back.",
            "Right-click a mod, a playset or a mod below the list for everything you can do with it.",
            "Not in this playset (below the list): installed mods that aren't in it. Double-click one, or select "
            "some and press Add to playset; Filter finds one quickly; Add all takes them all. Drag the gap above "
            "it to give it more or less room.",
            "New / Copy / Rename / Delete manage playsets. The first one is made from what the game currently "
            "loads.",
            "Import brings in a playset from the Paradox launcher (or what the game loads now); Export writes "
            "one back to the launcher (optional; close the launcher first, a backup is made).",
            "Compatibility (left) counts this playset's conflicts; click through to the Conflicts tab.",
        ]),
    ]),
    ("Auto-sort", [
        ("p", "Auto-sort works out the best order for the mods that are on, and shows you a preview before "
              "changing anything. Apply accepts it; undo puts the old order back."),
        ("p", "What it looks at, strongest first:"),
        ("bullets", [
            "your own rules, and mods that declare they need another mod;",
            "compatches, add-ons and translations named after another mod (they go after it), and compatches "
            "the Conflicts tab recognised (they go after both mods they patch);",
            "what the mods' Workshop pages say (\"load after X\", \"at the very bottom\", \"below total "
            "conversions\"), short names like \"Unop\" included;",
            "shared files where one mod's copy already contains the other's changes (it must load after);",
            "mods that use things only another mod defines (an add-on goes after its base);",
            "real clashes on shared files: the mod that would lose more of its work wins. Windows and map "
            "files count more than texts and pictures, and losing definitions a mod uses elsewhere counts a lot;",
            "if you tick it: mods made for an older game version first, so the newer ones win the files they "
            "share;",
            "fix packs (like the Unofficial Patch) and total conversions near the top, interface mods near the "
            "bottom (so other mods' copies of the game's windows don't replace theirs).",
        ]),
        ("p", "Mods that share nothing keep your order, since it makes no difference in game. The preview "
              "lists every mod that moves, how far, why (\"Because of\") and how sure it is:"),
        ("bullets", [
            "Certain: your own rules and dependencies a mod declares.",
            "Likely: evidence in the files (a merged file, a real clash, a recognised compatch) or on the "
            "Workshop page.",
            "Possible: weaker evidence, like a small clash or the older-versions-first setting.",
            "Convention: only the role's usual place; it makes no difference in game.",
        ]),
        ("tip", "\"Mods for older game versions load first\" is a tick in the preview (and in Settings > "
                "Sorting). It's off by default: a mod made for an older version isn't always worse."),
    ]),
    ("Conflicts", [
        ("p", "Everything that can go wrong between the mods that are on in your active playset, from serious "
              "to harmless. The list says what each conflict is and what solves it; click one for what you'll "
              "notice in game, what to do, why, and the mods involved (with Show in playset and Turn off)."),
        ("bullets", [
            "⊘ Critical: these mods don't work together (their pages say so), two total conversions or map "
            "mods, the same mod twice, or a mod missing one it needs. Fix these first.",
            "⚠ High: part of a mod is lost. Duplicate event IDs, on-action effects overwritten, the same new "
            "name used for different things, two mods replacing the same game window, a mod using things "
            "from a mod that's turned off, or one mod's copy of a game file leaving out things another uses.",
            "◆ Medium: both change the same parts of the game, the same game settings (defines) or the same "
            "interface pieces. The file names decide which version is used, not the load order, so only a "
            "compatibility patch (\"compatch\") can keep both.",
            "• Low: different wording of the same texts, older game versions, cosmetic files.",
            "✓ Info (\"Harmless ones\"): identical files, compatibility hooks, a compatch doing its job, and "
            "one mod adjusting another on purpose. Nothing to do.",
        ]),
        ("p", "Each conflict carries three labels: how serious it is, what solves it (Load order decides, "
              "Needs a compatch, Turn one off, Patched...) and how sure the app is (Certain, Likely, Possible)."),
        ("bullets", [
            "Compatches you already have are recognised (they need both mods, build on both, or are named "
            "for both). Their conflicts drop to Info, and Auto-sort loads the compatch after both mods. If "
            "the compatch is installed but off, the conflict offers to turn it on.",
            "Look for a compatch searches the Workshop for a patch made for the two mods and says how sure it "
            "is (it needs both mods: certain) and whether it may be outdated.",
            "Save compatch report writes a Markdown file with everything needed to make one: the two mods, "
            "the game's rules for combining them, each problem, and the objects they fight over side by side "
            "(with the game's own version). It ends with a prompt: paste it into an AI chat (Claude, ChatGPT...) "
            "together with the report, or send the report to a modder.",
            "Hide this conflict takes a conflict you've accepted out of the list and the counts. The Hidden "
            "switch shows hidden ones again (greyed), where you can unhide them; Settings > Sorting shows them "
            "all again at once.",
            "Right-click a conflict for the same actions.",
        ]),
        ("tip", "Typical fixes: a compatch (yours, from the Workshop, or one you have made from the report); or "
                "turn one mod off; or let Auto-sort pick the less damaging order when the clash is about shared "
                "files."),
    ]),
    ("Crashes", [
        ("p", "When the game crashes it leaves a report (in Documents\\Paradox Interactive\\<game>\\crashes). "
              "The app finds it, shows a bar when you next open it, counts it on the tab, and works out which mods "
              "are most likely to blame."),
        ("h", "How it decides"),
        ("p", "The game's crash report can't name a mod (its stack trace has no names), so the evidence is the "
              "session's error log. Each error is traced to the mod whose file it points at (the copy the game "
              "really loaded) and weighed by kind:"),
        ("bullets", [
            "Files that don't load (typos, missing braces, an outdated format) and broken events count the most.",
            "Things a mod uses that the game doesn't have: removed or renamed traits, events, buildings, "
            "modifiers. The game's own rename tables explain renames (\"scholar\" became \"erudite\" in 1.20).",
            "When a mod's copy of a game file leaves something out that others use, the blame goes to that mod, "
            "not to the mods that hit the gap.",
            "The game's own checks failing (\"assertion failed\"), broken definitions (traits, modifiers, "
            "buildings) and interface files that don't work count strongly.",
            "Errors in the last moments before the crash count more; missing pictures and texts hardly at all.",
            "The playset's conflicts (from the Conflicts tab), missing required mods and mods made for an older "
            "game version add to it.",
        ]),
        ("h", "Every crash and every game that worked"),
        ("p", "The app remembers every crash and every game that ended well, with the mods each had (the game's "
              "own log lists them). That's often the strongest evidence:"),
        ("bullets", [
            "A mod that was in a game that worked, and hasn't changed since, is cleared (Unlikely).",
            "A mod that has never been in a game that worked stands out, more so when few mods are like that.",
            "So does a mod installed or updated after your last game that worked, or in the days before the crash.",
            "A mod in every crash at the same stage (while setting up the world, drawing the interface, playing) "
            "counts more. For start-up crashes, mods the game got past start-up with (in a crash later on) "
            "count less.",
            "Mods you've since uninstalled are still suspects, by name (\"not installed now\").",
            "Your answers in Find the culprit are remembered as crashes or games that worked.",
        ]),
        ("tip", "Play once without crashing (and quit from the game's menu) after changing mods: that game is what "
                "clears the mods that are fine."),
        ("p", "Each suspect is Likely, Possible or Unlikely, compared with the strongest one. Its details show "
              "why, what to try, the things it uses that don't exist, its conflicts (with Look for a compatch and "
              "Save compatch report), and samples of its errors. Turn it off, show it in the playset or Library, "
              "or copy its errors. \"Every mod\" lists the whole load order of that game."),
        ("h", "Find the culprit"),
        ("p", "When the logs can't tell, Find the culprit narrows it down by halves: it makes a copy of your "
              "playset called \"Crash test\" (yours isn't changed), turns about half of the suspects off there "
              "(the likeliest first, with the mods that need them), and you start the game with Play and answer "
              "\"It crashed\" or \"It didn't crash\". A few rounds later one mod is left; turn it off in your "
              "playset or go back to it as it was. With 80 mods it takes about 7 rounds."),
        ("bullets", [
            "Save crash report writes a Markdown file with everything found, ending with a prompt for an AI chat "
            "(or share it with the mod authors).",
            "Last session's errors (in the menu at the top) reads the last game you played the same way, even "
            "when it didn't crash.",
            "The folder and bin buttons open or delete a crash's folder (logs, a memory dump and a copy of your "
            "save from that moment; your real saves aren't touched).",
            "Mods that are suspects are marked in Library, Playsets and the Conflicts tab, with a link back here.",
        ]),
        ("tip", "If the crash happened inside a graphics driver (the summary says so), update or reinstall the "
                "driver before blaming mods."),
    ]),
    ("Roles and icons", [
        ("p", "Every mod gets a role from clues, weighed together: what its files change (the most: how much it "
              "changes compared with the game, not just which folders it has), what its files prove (a new map, "
              "replaced history, small edits of the game's own files, the mods it needs or builds on), its title, "
              "its Workshop description and the categories its author ticked on the Workshop. Those ticks count "
              "less the more of them there are, and \"Total conversion\" needs proof in the files: a tick alone "
              "never makes one. A mod's details list the clues; you can always set the role yourself. The badge "
              "next to its picture shows it:"),
        ("roles", None),
        ("p", "\"Achievement-friendly\" in a mod's details means it changes nothing the game checksums, so "
              "Ironman and achievements keep working."),
    ]),
    ("Play", [
        ("p", "Play writes your playset's mods, in order, into the file the game reads at start "
              "(dlc_load.json in the game's Documents folder; your old one is backed up to .work\\backups) "
              "and starts the game the same way the Paradox launcher does. Your DLC settings stay as they are."),
        ("bullets", [
            "Before starting, it warns about missing mods and critical conflicts (you can still go ahead).",
            "The game's install folder is found through Steam and GOG. If it isn't, Play asks you once, or "
            "set it in Settings > Games.",
            "A Steam copy of the game needs Steam running. If the game closes right away, a bar offers to start "
            "Steam.",
            "If you open the official launcher later and press Play there, it uses its own playset instead. "
            "Nothing breaks; just use one or the other.",
        ]),
    ]),
    ("Settings", [
        ("p", "Settings has a section for each kind of choice, listed on its left. Nothing changes until you "
              "press Save."),
        ("bullets", [
            "General: where other games' mods go, skipping mods you already have, adding new mods to the active "
            "playset, asking about the mods a mod needs, and the check window for \"verify you are human\".",
            "Games: for each game, its install folder (Find looks for it) and \"I own it on Steam\".",
            "Sorting: whether Auto-sort reads the mods' Workshop pages, \"mods for older game versions load "
            "first\", and showing all hidden conflicts again.",
            "Download sites: switch sites in the chain on or off and reorder them (at least one stays on). The "
            "Steam switch is for the current game: off when you don't own it on Steam.",
            "Accounts: your Steam account name (for games you own there), a mod.io key, a GitHub token. All "
            "optional.",
            "Storage: how much room cached pictures and Workshop pages may take before the app offers to clear "
            "them (100 MB to 10 GB, 250 MB to start with), and Clear now.",
            "Appearance: the palette (Classic, or Colorful: warm parchment and royal tones, every tab in its "
            "own colour, a heraldic ribbon under the top bar), light or dark, and Reset panel sizes. A new "
            "palette applies after a restart, which the app offers to do.",
            "About: the version, What's new, the app's folder and the project page on GitHub.",
        ]),
    ]),
    ("Words you'll see", [
        ("bullets", [
            "Workshop ID: the number at the end of a mod's Steam link (?id=2871648329).",
            "Collection: a Workshop list of many mods; catching it catches all of them.",
            "Mod folder: Documents\\Paradox Interactive\\<game>\\mod, where mods live.",
            ".mod file / descriptor: the small file that tells the game a mod exists, its name and version.",
            "Vanilla: the game without mods.",
            "Override: a mod replacing one of the game's files or definitions with its own.",
            "Load order / playset: see Playsets.",
            "Compatch (compatibility patch): a small mod that makes two other mods work together; it loads "
            "after both.",
            "Compatch report: a Markdown file the Conflicts tab writes with everything needed to make a "
            "compatch, ending with a prompt for an AI chat.",
            "Define: one of the game's numeric settings (common/defines). Two mods setting the same one: the "
            "file whose name sorts later wins.",
            "Submod / add-on: a mod built on top of another mod; it needs that mod.",
            "Total conversion: a mod that replaces the game world (map, history, cultures).",
            "Checksum / Ironman: the game's way to tell if a game is modded; checksummed changes turn off "
            "achievements.",
            "SteamCMD: Valve's command-line downloader the app uses for Steam.",
            "Owned on Steam: the game is in your Steam library. Only then does Steam hand out its Workshop files.",
        ]),
    ]),
    ("When something goes wrong", [
        ("h", "A mod says \"Not found\""),
        ("p", "No enabled site had it. not_found.txt (next to the app) lists each site's reason. Steam refuses "
              "mods of games your account doesn't own; SkyMods may need its human check; some mods simply "
              "aren't mirrored anywhere."),
        ("h", "My internet dropped / I closed the app mid-download"),
        ("p", "Press Resume (or Resume on the yellow bar when the app starts). Downloads continue where they "
              "stopped."),
        ("h", "A mod landed in the downloads folder, not the mod folder"),
        ("p", "It's for another game than the one picked at the top. Mods are matched to the game by Steam's own "
              "game number, so this only happens when the mod really is for another game."),
        ("h", "The game doesn't start"),
        ("p", "Check that Steam is running (for a Steam copy), and that Settings > Games points at the game's "
              "install folder. The arrow next to Play > Open the game's error log shows what the game complained "
              "about."),
        ("h", "The game crashes"),
        ("p", "Open the Crashes tab: it names the mods most likely to blame, with the evidence. If no mod stands "
              "out, Find the culprit narrows it down by turning half of the suspects off at a time."),
        ("h", "My mods don't show up in the game"),
        ("p", "Make sure they're ticked On in the playset you start, and start the game with Play here. "
              "The official launcher uses its own playset."),
        ("h", "\"Game folder unknown\" in the analysis"),
        ("p", "Set the game's install folder in Settings > Games. Without it the app can't compare mods with "
              "the game's own files, so conflicts and roles are less precise."),
        ("h", "Browse shows nothing"),
        ("p", "Browse needs internet access to steamcommunity.com. If Steam changes its Workshop page, browsing "
              "may stop working until the app is updated; Catch still works with links."),
        ("h", "A red bar says something went wrong"),
        ("p", "The app caught an unexpected error and carried on. The details are in .work\\errors.log next to "
              "the app; include that file if you report the problem."),
    ]),
    ("Files next to the app", [
        ("bullets", [
            "settings.json: your choices.  profiles.json: your playsets.",
            "installed.json: what was installed from where.  updates.json: the last update check.",
            "not_found.txt: mods no site had, with each site's reason.  catch_list.json: your catch list.",
            "crash_history.json: every crash and every game that worked, with their mods (the Crashes tab uses it).",
            "steamcmd\\: Valve's downloader.",
            ".work\\: downloads in progress and the resume queue, backups of the game's mod list, cached "
            "Workshop pages and pictures, the game's own definitions (read once per game version), the last "
            "analysis of your mods (analysis_cache.pkl, used again while nothing changes) and errors.log.",
            "Cached pictures, screenshots and Workshop pages only take room: when they pass your limit "
            "(Settings > Storage, 250 MB unless you change it) the app offers to clear them at start. They come "
            "back by themselves when needed.",
            "Move the app with these files and nothing is lost. Delete them all for a fresh start.",
        ]),
    ]),
]

WHATS_NEW_INTRO = ("The biggest update so far: conflicts you can act on, a smarter Auto-sort, playset rules, and a "
                   "lot of small things that make every tab easier.")
# (title, icon, lines); titles that name a tab use that tab's colour in the Colorful palette
WHATS_NEW = [
    ("Conflicts", "conflicts", [
        "Each conflict says what you'll notice in game, what solves it (load order, a compatch, turning one off) "
        "and how sure the app is.",
        "New checks: two mods setting the same game value (defines), the same interface template or type, and a "
        "mod's copy of a game file leaving out things another mod uses. Shared-file clashes list the exact "
        "objects each side loses.",
        "Compatches you have are recognised: their conflicts become harmless and Auto-sort loads them after both "
        "mods. An installed compatch that's turned off is offered to you.",
        "Look for a compatch searches the Workshop for one, saying how sure it is and whether it may be outdated.",
        "Save compatch report writes everything needed to make a compatch, with both mods' versions side by side "
        "and a ready prompt for an AI chat.",
        "Hide conflicts you've accepted; right-click menu.",
    ]),
    ("Playsets", "playsets", [
        "Auto-sort 2: says how sure it is of each move, places recognised compatches after both mods they "
        "patch, keeps fix packs near the top and interface mods near the bottom.",
        "New option: mods made for older game versions load first, so newer ones win the files they share.",
        "Rules at the top of a mod's details: First, Early, Late or Last, and \"loads after / before\" another mod. "
        "Clear one mod's rules, or all of them.",
        "Turn off, Remove, Open folder and Delete right in the details, and right-click menus.",
    ]),
    ("Library", "library", [
        "Show one playset's mods (yours, or the official launcher's), and sort the enabled ones first.",
        "Roles are worked out from weighed clues and explained; set a mod's role yourself when you disagree. "
        "Mods that tick \"Total conversion\" on the Workshop aren't called one without proof in their files.",
    ]),
    ("Browse", "browse", [
        "Searches show the best matches first (title, then author, then description), and a refresh button.",
        "Every screenshot of a mod, and a picture viewer inside the app.",
        "When a mod needs other Workshop mods, you're asked whether to catch them too.",
    ]),
    ("Catch", "download", [
        "The catch list is kept between sessions and shown in full: download or remove each mod, or all at once.",
        "Pasted links and collections go on the catch list instead of downloading at once; Library's Catch All "
        "adds every mod with an update. Caught mods with a newer version are updated, not skipped.",
        "Downloads that didn't work can be retried one by one or all together.",
    ]),
    ("Crashes", "crash", [
        "A new tab. After a crash it says what the game was doing and names the mods most likely to blame, with "
        "the evidence: files that don't load, things they use that this game version doesn't have (renamed "
        "traits explained), what one mod's copy of a game file leaves out for others, conflicts, missing "
        "required mods, older versions.",
        "Find the culprit: turns half of the suspects off in a copy of your playset, you play and answer, and a "
        "few rounds later one mod is left.",
        "Crash reports for an AI chat or the mod authors; suspects are marked in Library, Playsets and Conflicts.",
        "Every crash and every game that worked is remembered with its mods: mods that were in a game that "
        "worked are cleared, mods that never were (or changed just before) stand out, uninstalled ones too.",
    ]),
    ("Everywhere", "sparkle", [
        "Rescan and Check updates are in the top bar, so they work from every tab.",
        "Right-click menus in every list. Column dividers move the edge you drag, and widths are remembered.",
        "Cached pictures and pages have a size limit you choose; above it the app offers to clear them.",
        "Redesigned Settings, and a new Colorful palette (Settings > Appearance).",
        "Search boxes have an x to clear them; the Help topics scroll on small windows.",
    ]),
]


def role_lines():
    return [(r, f"{r.name}: {r.blurb}.") for r in R.ROLES]
