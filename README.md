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
