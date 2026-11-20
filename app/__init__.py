"""
Adromedary's Paradoxical Launcher: the app's code. paradoxical_launcher.py (one folder up) starts it.

    core/      mods, games, DLC, playsets, updates: no windows
    online/    Steam, the Workshop, downloads
    analysis/  reading mods against the game: conflicts, saved checks, roles, crashes
    gui/       every tab and window, the palettes, icons and Help
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the folder with paradoxical_launcher.py
