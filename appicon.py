"""
The app's icon (icon.ico: Adromedary's crest), used for the .exe, the taskbar, every window's title
bar and the pictures inside the app (splash, header, welcome, What's new).

icon.ico sits next to the source; in the built .exe it's bundled (build.bat: --add-data) and found in
PyInstaller's unpack folder.
"""
import os
import sys

ICON_FILE = "icon.ico"
_cache = {}


def icon_path():
    """Where icon.ico is: the .exe's bundle, next to this file, or next to the .exe. '' if missing."""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (getattr(sys, "_MEIPASS", ""), here, os.path.dirname(os.path.abspath(sys.executable))):
        if d:
            p = os.path.join(d, ICON_FILE)
            if os.path.isfile(p):
                return p
    return ""


def _master():
    """The largest image in icon.ico, as RGBA."""
    if "master" not in _cache:
        from PIL import Image                   # imported here: without Pillow the app still runs, iconless
        im = Image.open(icon_path())
        sizes = im.info.get("sizes") or {im.size}
        im.size = max(sizes)
        im.load()
        _cache["master"] = im.convert("RGBA")
    return _cache["master"]


def render(size=256):
    """The icon as an RGBA image of the given size."""
    from PIL import Image
    key = ("r", size)
    if key not in _cache:
        m = _master()
        _cache[key] = m if m.size == (size, size) else m.resize((size, size), Image.LANCZOS)
    return _cache[key]


def apply(window, app_dir=None):
    """Give a Tk/CTk window (or dialog) the app icon. Never raises."""
    try:
        path = icon_path()
        if sys.platform.startswith("win") and path:
            if window.winfo_toplevel() is window and window.master is None:
                window.iconbitmap(default=path)  # the main window: also the default for every dialog
            window.iconbitmap(path)             # also stops customtkinter replacing it with its own
            # customtkinter sets its own icon a moment after a Toplevel opens: set ours again after it
            window.after(260, lambda: _safe(window.iconbitmap, path))
        else:
            from PIL import ImageTk
            img = ImageTk.PhotoImage(render(64))
            window.iconphoto(True, img)
            window._pmc_icon = img              # keep a reference or Tk drops the image
    except Exception:
        pass


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass
