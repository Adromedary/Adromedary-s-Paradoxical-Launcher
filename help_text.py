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
            "list and big picture panels. Or paste Steam Workshop links into Catch if you already have them.",
            "Press Catch now on a mod (or double-click it). It downloads and installs by itself while you keep "
            "browsing; its row shows the progress and then ✓ Installed.",
            "Open Playsets. Your mods are listed in the order the game loads them. Tick the ones you want, then "
            "press Auto-sort to put them in a good order.",
            "Look at Conflicts. It tells you, in plain words, if some of your mods don't get along.",
            "Press Play at the top. The game starts with exactly those mods.",
        ]),
        ("tip", "Mods are installed into Documents\\Paradox Interactive\\<game>\\mod, the same place the "
                "official launcher uses. The game's own files are never changed."),
        ("tip", "Every list has a detail panel on its right. Drag the gap between them to make either one wider; "
                "the app remembers it. In Playsets, the gap above \"Not in this playset\" can be dragged too."),
        ("tip", "When the app starts, a short loading screen reads your mods, checks them and draws every list, so "
                "everything is ready when the window opens. The check is remembered: as long as your mods don't "
                "change, the next start takes a few seconds."),
        ("tip", "Rest the pointer on a button without text (arrows, undo, the moon, ?) to see what it does."),
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
            "The moon / sun button switches dark and light look, ? opens this help on the page for the tab "
            "you're on, Settings holds the rest.",
            "The tabs: Browse (find mods), Catch (download), Library (what you have), Playsets (what you play "
            "with, in which order), Conflicts (what clashes). A small number on a tab counts what needs you: "
            "downloads going on, updates waiting, serious conflicts.",
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
            "Search: type a name, an author or words from the description and press Enter.",
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
            "list sits bottom right; Catch them downloads them all.",
            "The details show the mod's pictures, its description and the other mods it needs, each marked "
            "✓ if you have it. \"Catch it with the missing\" fetches the mod and what it needs in one go.",
            "Steam page opens the mod in your web browser; In Library jumps to your copy of it.",
            "In the details, click one of the mod's categories to show only mods of that category.",
        ]),
    ]),
    ("Catch: download", [
        ("p", "Catch downloads mods and installs them. Mods caught in Browse run here; you can also paste Steam "
              "Workshop links or IDs yourself, one per line (pasting always starts a new line), and press Start."),
        ("bullets", [
            "Collections are opened up into their mods (also collections inside collections).",
            "The chain: each mod is tried on Steam first, then SkyMods, mod.io, Thunderstore, ModDB, GitHub "
            "and steamworkshop.download, until one has it. Steam is left out for games you don't own there. "
            "Settings > Download sites switches sites off or reorders them.",
            "N at a time: how many mods download at once (1 to 5).",
            "Pause keeps what's downloaded so far; Resume continues each file where it stopped, even after "
            "closing the app. Cancel stops and throws partial downloads away.",
            "The queue shows each mod: Queued, Working (with %), Done, Have it (already installed, also when "
            "Steam installed it for you), Not found (no site had it; not_found.txt says why), Paused, Interrupted "
            "(the connection kept dropping; Resume picks it up).",
            "Links that finished leave the box; links that failed stay so you can try again. What's in the box "
            "is kept when you close the app.",
            "Show log tells you step by step what happened. Mod folder opens it.",
            "Freshly downloaded mods are added to your active playset automatically (Settings > Downloads).",
        ]),
        ("h", "\"Verify you are human\" (SkyMods)"),
        ("p", "SkyMods' file host shows a Cloudflare check on downloads. With the check window on (Settings > "
              "Downloads), the page opens in a small hidden browser window. If the check passes by itself you "
              "see nothing; if it wants a click, the window appears and a yellow bar tells you. Tick the box "
              "yourself (the app never does it for you) and it carries on. Unanswered for 5 minutes, SkyMods "
              "is skipped for that run."),
    ]),
    ("Library: your mods", [
        ("p", "Every mod in the mod folder, with its picture and a role badge saying what kind of mod it is."),
        ("bullets", [
            "Notes column: ⚠ shares files with another mod, ○ made for another game version, "
            "↻ a newer version is on the Workshop, ✗ its folder is missing. Playset column: ✓ on "
            "in the active playset, \"off\" listed but turned off.",
            "Search, the All / Conflicts / Updates / Version filters, the role filter and Sort narrow the list. "
            "Click a column heading to sort by it.",
            "Click a mod for its details: what it is and why, whether it's achievement-friendly, possible "
            "conflicts with other installed mods, and the exact files it shares (selectable, Copy paths).",
            "Its buttons: Update (when there is one), Add to playset or In playset, Steam page, Open folder, "
            "Ignore conflicts (leaves it out of the shared-file warnings) and Delete (asks first).",
            "Check updates asks Steam which mods changed. Update or Update all downloads the new version; "
            "the old copy is deleted only after the new one is installed.",
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
            "Click a mod: its role, its conflicts, why it sits where it does, which files it wins or loses, "
            "which other mods it uses or is used by, and your own rules (\"Add a rule...\": this loads after it / "
            "before it), which Auto-sort always keeps.",
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
            "compatches, add-ons and translations named after another mod (they go after it);",
            "what the mods' Workshop pages say (\"load after X\", \"at the very bottom\", \"below total "
            "conversions\"), short names like \"Unop\" included;",
            "shared files where one mod's copy already contains the other's changes (it must load after);",
            "mods that use things only another mod defines (an add-on goes after its base);",
            "real clashes on shared files: the mod that would lose more of its work wins. Windows and map "
            "files count more than texts and pictures, and losing definitions a mod uses elsewhere counts a lot;",
            "fix packs (like the Unofficial Patch) and total conversions near the top.",
        ]),
        ("p", "Mods that share nothing keep your order, since it makes no difference in game. The preview "
              "lists every mod that moves, how far, and why (\"Because of\")."),
    ]),
    ("Conflicts", [
        ("p", "Everything that can go wrong between the mods that are on in your active playset, from serious "
              "to harmless. Each entry explains what happens in game and what you can do, with Turn off and "
              "Show buttons for the mods involved."),
        ("bullets", [
            "⊘ Critical: these mods don't work together (their pages say so), two total conversions or map "
            "mods, the same mod twice, or a mod missing one it needs. Fix these first.",
            "⚠ High: part of a mod is lost. Duplicate event IDs, on-action effects overwritten, the same new "
            "name used for different things, two mods replacing the same game window, or a mod using things "
            "from a mod that's turned off.",
            "◆ Medium: both change the same parts of the game. The file names decide which version is "
            "used, not the load order, so only a compatibility patch (\"compatch\") can keep both.",
            "• Low: different wording of the same texts, older game versions, cosmetic files.",
            "✓ Info (\"Show harmless ones too\"): identical files, compatibility hooks and one mod adjusting "
            "another on purpose. Nothing to do.",
        ]),
        ("tip", "Typical fixes: \"Look for a compatch\" searches the Workshop for a patch made for the "
                "two mods; or turn one of them off; or let Auto-sort pick the less damaging order when the clash "
                "is about shared files."),
    ]),
    ("Roles and icons", [
        ("p", "Every mod gets a role from what its files actually do (how much it changes compared with the "
              "game, not just which folders it has). The badge next to its picture shows it:"),
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
        ("bullets", [
            "Download sites: switch sites in the chain on or off and reorder them (at least one stays on). The "
            "Steam switch is for the current game: off when you don't own it on Steam.",
            "Accounts: your Steam account name (for games you own there), a mod.io key, a GitHub token. All "
            "optional.",
            "Downloads: where other games' mods go, skipping mods you already have, adding new mods to the "
            "active playset, the check window for \"verify you are human\".",
            "Games: for each game, its install folder (Find looks for it) and \"I own it on Steam\". Also whether "
            "Auto-sort reads the mods' Workshop pages.",
            "Appearance: Light, Dark, or System (follows Windows), and Reset panel sizes.",
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
            "not_found.txt: mods no site had, with each site's reason.",
            "steamcmd\\: Valve's downloader.",
            ".work\\: downloads in progress and the resume queue, backups of the game's mod list, cached "
            "Workshop pages and pictures, the game's own definitions (read once per game version), the last "
            "analysis of your mods (analysis_cache.pkl, used again while nothing changes) and errors.log.",
            "Move the app with these files and nothing is lost. Delete them all for a fresh start.",
        ]),
    ]),
]


def role_lines():
    return [(r, f"{r.name}: {r.blurb}.") for r in R.ROLES]
