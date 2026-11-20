"""
Files saved by 2.2 and before, when every module sat in one folder: their pickles name classes by the
old module names ("analysis.Issue"). Reading them through here finds the classes where they are now,
so saved playset checks, mods' facts and remembered roles survive the move to folders.
"""
import pickle

MOVED = {
    "engine": "app.core.engine", "installer": "app.core.installer", "launcher": "app.core.launcher",
    "modscan": "app.core.modscan", "loadorder": "app.core.loadorder", "profiles": "app.core.profiles",
    "storage": "app.core.storage", "updates": "app.core.updates", "versions": "app.core.versions",
    "dlcs": "app.core.dlcs", "script": "app.core.script",
    "net": "app.online.net", "sources": "app.online.sources", "workshop": "app.online.workshop",
    "compat": "app.online.compat", "browser_helper": "app.online.browser_helper",
    "analysis": "app.analysis.analysis", "gamedb": "app.analysis.gamedb", "checks": "app.analysis.checks",
    "report": "app.analysis.report", "crash": "app.analysis.crash", "roles": "app.analysis.roles",
    "gui_common": "app.gui.common", "gui_browse": "app.gui.browse", "gui_catch": "app.gui.catch",
    "gui_library": "app.gui.library", "gui_playsets": "app.gui.playsets", "gui_dlc": "app.gui.dlc",
    "gui_conflicts": "app.gui.conflicts", "gui_crash": "app.gui.crash", "gui_viewer": "app.gui.viewer",
    "cards": "app.gui.cards", "glyphs": "app.gui.glyphs", "icons": "app.gui.icons",
    "appicon": "app.gui.appicon", "help_text": "app.gui.help_text",
}


class Unpickler(pickle.Unpickler):
    """pickle.Unpickler that also reads pickles written before the move to folders."""

    def find_class(self, module, name):
        return super().find_class(MOVED.get(module, module), name)


def load(fh):
    """pickle.load, for files that may have been written before the move."""
    return Unpickler(fh).load()
