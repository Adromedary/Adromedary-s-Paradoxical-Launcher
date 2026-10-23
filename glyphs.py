"""
The app's interface icons, drawn with Pillow as simple line pictures on a 24-unit grid.

Fonts can't be trusted for symbols: on Windows, Tk shows a '?' for characters that only exist in
colour-emoji fonts (download arrows, magnifiers, sparkles, pause signs...). Drawing them avoids that and
keeps every icon the same weight. Each icon is drawn at 4x its size and smoothed down.
"""
import math
import threading

try:
    from PIL import Image, ImageDraw
except Exception:                       # pragma: no cover
    Image = None

_cache, _lock = {}, threading.Lock()
STROKE = 2.0                            # line width in grid units


def available():
    return Image is not None


class _Pen:
    def __init__(self, size, color):
        self.N = size * 4
        self.k = self.N / 24.0
        self.img = Image.new("RGBA", (self.N, self.N), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.c = color
        self.w = max(1, int(round(STROKE * self.k)))

    def p(self, x, y):
        return (x * self.k, y * self.k)

    def cap(self, x, y, w=None):
        r = (w or self.w) / 2.0
        X, Y = self.p(x, y)
        self.d.ellipse((X - r, Y - r, X + r, Y + r), fill=self.c)

    def line(self, *pts, close=False, w=None):
        pts = list(pts) + ([pts[0]] if close else [])
        P = [self.p(*q) for q in pts]
        self.d.line(P, fill=self.c, width=w or self.w, joint="curve")
        for q in pts:
            self.cap(*q, w=w)

    def circle(self, cx, cy, r, fill=False):
        X, Y = self.p(cx, cy)
        R = r * self.k
        if fill:
            self.d.ellipse((X - R, Y - R, X + R, Y + R), fill=self.c)
        else:
            self.d.ellipse((X - R, Y - R, X + R, Y + R), outline=self.c, width=self.w)

    def arc(self, cx, cy, r, start, end):
        X, Y = self.p(cx, cy)
        R = r * self.k
        self.d.arc((X - R, Y - R, X + R, Y + R), start, end, fill=self.c, width=self.w)
        for a in (start, end):
            self.cap(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))

    def rect(self, x, y, w, h, r=2.0, fill=False):
        box = (*self.p(x, y), *self.p(x + w, y + h))
        if fill:
            self.d.rounded_rectangle(box, radius=r * self.k, fill=self.c)
        else:
            self.d.rounded_rectangle(box, radius=r * self.k, outline=self.c, width=self.w)

    def poly(self, *pts):
        self.d.polygon([self.p(*q) for q in pts], fill=self.c)

    def head(self, x, y, dx, dy, length=4.0, spread=42):
        """Arrowhead with its tip at (x, y) pointing along (dx, dy)."""
        a = math.atan2(dy, dx)
        pts = []
        for s in (spread, -spread):
            b = a + math.pi - math.radians(s)
            pts.append((x + length * math.cos(b), y + length * math.sin(b)))
        self.line(pts[0], (x, y), pts[1])

    def erase_circle(self, cx, cy, r):
        X, Y = self.p(cx, cy)
        R = r * self.k
        mask = Image.new("L", self.img.size, 255)
        ImageDraw.Draw(mask).ellipse((X - R, Y - R, X + R, Y + R), fill=0)
        alpha = self.img.getchannel("A")
        from PIL import ImageChops
        self.img.putalpha(ImageChops.multiply(alpha, mask))


# ------------------------------------------------------------------ the icons (24 x 24 grid)
def _search(p):
    p.circle(10.5, 10.5, 6.5)
    p.line((15.5, 15.5), (20.5, 20.5))


def _download(p):
    p.line((12, 3.5), (12, 14.5))
    p.line((7.5, 10), (12, 14.5), (16.5, 10))
    p.line((4, 15.5), (4, 19.5), (20, 19.5), (20, 15.5))


def _upload(p):
    p.line((12, 14.5), (12, 3.5))
    p.line((7.5, 8), (12, 3.5), (16.5, 8))
    p.line((4, 15.5), (4, 19.5), (20, 19.5), (20, 15.5))


def _globe(p):
    p.circle(12, 12, 9)
    X0, Y0 = p.p(8, 3)
    X1, Y1 = p.p(16, 21)
    p.d.ellipse((X0, Y0, X1, Y1), outline=p.c, width=p.w)
    p.line((3.5, 12), (20.5, 12))


def _library(p):
    p.rect(3.5, 4, 4, 16, r=1)
    p.rect(9.5, 4, 4, 16, r=1)
    p.line((15.5, 5.2), (19.2, 4.3), (21.8, 19.0), (18.1, 19.9), close=True)


def _playsets(p):
    p.line((3, 6), (16, 6))
    p.line((3, 12), (13, 12))
    p.line((3, 18), (10, 18))
    p.poly((14.5, 13.5), (14.5, 22), (21.5, 17.75))


def _alert(p):
    p.line((12, 3.5), (21.5, 20), (2.5, 20), close=True)
    p.line((12, 9.5), (12, 13.5))
    p.circle(12, 16.8, 1.3, fill=True)


def _play(p):
    p.poly((7, 4), (19.5, 12), (7, 20))


def _gear(p):
    cx = cy = 12
    pts = []
    teeth = 8
    for i in range(teeth * 4):
        a = 2 * math.pi * i / (teeth * 4) - math.pi / 2
        r = 10.2 if (i % 4) in (1, 2) else 7.6
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    p.poly(*pts)
    p.erase_circle(cx, cy, 3.4)


def _help(p):
    p.circle(12, 12, 9.5)
    p.arc(12, 9.6, 3.1, 180, 400)
    a = math.radians(40)
    p.line((12 + 3.1 * math.cos(a), 9.6 + 3.1 * math.sin(a)), (12, 13.6))
    p.circle(12, 17.2, 1.3, fill=True)


def _info(p):
    p.circle(12, 12, 9.5)
    p.line((12, 11), (12, 16.5))
    p.circle(12, 7.6, 1.3, fill=True)


def _moon(p):
    p.circle(11.5, 12.5, 8.5, fill=True)
    p.erase_circle(16.3, 8.2, 7.2)


def _sun(p):
    p.circle(12, 12, 4)
    for i in range(8):
        a = math.radians(i * 45)
        p.line((12 + 7 * math.cos(a), 12 + 7 * math.sin(a)), (12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a)))


def _external(p):
    p.line((14, 3.5), (20.5, 3.5), (20.5, 10))
    p.line((20.5, 3.5), (11, 13))
    p.line((18, 14), (18, 20.5), (3.5, 20.5), (3.5, 6), (10, 6))


def _refresh(p):
    p.arc(12, 12, 8, 50, 320)
    a = math.radians(320)
    x, y = 12 + 8 * math.cos(a), 12 + 8 * math.sin(a)
    p.head(x, y, -math.sin(a) * -1, math.cos(a) * 1)


def _plus(p):
    p.line((12, 5), (12, 19))
    p.line((5, 12), (19, 12))


def _minus(p):
    p.line((5, 12), (19, 12))


def _close(p):
    p.line((6, 6), (18, 18))
    p.line((18, 6), (6, 18))


def _check(p):
    p.line((4.5, 12.5), (9.5, 17.5), (19.5, 6.5))


def _trash(p):
    p.line((3.5, 6.5), (20.5, 6.5))
    p.line((9, 6.5), (9, 4), (15, 4), (15, 6.5))
    p.line((5.5, 6.5), (6.5, 20.5), (17.5, 20.5), (18.5, 6.5))
    p.line((10, 10.5), (10, 16.5))
    p.line((14, 10.5), (14, 16.5))


def _folder(p):
    p.line((3, 6), (9, 6), (11, 8.5), (21, 8.5), (21, 19), (3, 19), close=True)


def _undo(p):
    p.line((9, 4.5), (4.5, 9), (9, 13.5))
    p.line((4.5, 9), (14.5, 9))
    p.arc(14.5, 14.25, 5.25, 270, 450)
    p.line((14.5, 19.5), (10, 19.5))


def _redo(p):
    p.line((15, 4.5), (19.5, 9), (15, 13.5))
    p.line((19.5, 9), (9.5, 9))
    p.arc(9.5, 14.25, 5.25, 90, 270)
    p.line((9.5, 19.5), (14, 19.5))


def _up(p):
    p.line((6, 15), (12, 9), (18, 15))


def _down(p):
    p.line((6, 9), (12, 15), (18, 9))


def _left(p):
    p.line((15, 6), (9, 12), (15, 18))


def _right(p):
    p.line((9, 6), (15, 12), (9, 18))


def _top(p):
    p.line((5, 3.5), (19, 3.5))
    p.line((12, 8.5), (12, 20.5))
    p.line((6.5, 14), (12, 8.5), (17.5, 14))


def _bottom(p):
    p.line((5, 20.5), (19, 20.5))
    p.line((12, 15.5), (12, 3.5))
    p.line((6.5, 10), (12, 15.5), (17.5, 10))


def _sparkle(p):
    p.poly((10, 3), (12, 10), (19, 12), (12, 14), (10, 21), (8, 14), (1.5, 12), (8, 10))
    p.poly((19, 2.5), (19.9, 5.1), (22.5, 6), (19.9, 6.9), (19, 9.5), (18.1, 6.9), (15.5, 6), (18.1, 5.1))


def _pause(p):
    p.rect(5.5, 4, 4.5, 16, r=1.2, fill=True)
    p.rect(14, 4, 4.5, 16, r=1.2, fill=True)


def _stop(p):
    p.rect(5, 5, 14, 14, r=2.5, fill=True)


def _list(p):
    for y in (6, 12, 18):
        p.line((8.5, y), (20.5, y))
        p.circle(4, y, 1.4, fill=True)


def _grid(p):
    for x, y in ((3.5, 3.5), (13.5, 3.5), (3.5, 13.5), (13.5, 13.5)):
        p.rect(x, y, 7, 7, r=1.5)


def _power(p):
    p.arc(12, 13, 8, 300, 600)
    p.line((12, 3), (12, 11))


def _copy(p):
    p.rect(8.5, 8.5, 12, 12, r=2)
    p.line((15.5, 8.5), (15.5, 4), (3.5, 4), (3.5, 15.5), (8.5, 15.5))


def _filter_off(p):
    p.line((3, 4.5), (21, 4.5), (14, 12.5), (14, 19.5), (10, 21), (10, 12.5), close=True)


def _layers(p):
    p.line((12, 3), (21, 8), (12, 13), (3, 8), close=True)
    p.line((3, 12.5), (12, 17.5), (21, 12.5))
    p.line((3, 17), (12, 22), (21, 17))


def _star(p):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = 9.5 if i % 2 == 0 else 4.2
        pts.append((12 + r * math.cos(a), 12.6 + r * math.sin(a)))
    p.poly(*pts)


def _bars(p):
    p.line((5, 20), (5, 13))
    p.line((12, 20), (12, 5))
    p.line((19, 20), (19, 10))


def _wand(p):
    p.line((4, 20), (14.5, 9.5))
    p.poly((17, 3), (17.8, 5.6), (20.5, 6.5), (17.8, 7.4), (17, 10), (16.2, 7.4), (13.5, 6.5), (16.2, 5.6))


def _steam(p):
    p.circle(12, 12, 9.5)
    p.circle(15, 9.5, 2.8)
    p.line((5, 14.5), (10, 16.5))
    p.circle(10.5, 15.5, 1.6, fill=True)


def _log(p):
    p.rect(4, 3, 16, 18, r=2)
    p.line((8, 8), (16, 8))
    p.line((8, 12), (16, 12))
    p.line((8, 16), (13, 16))


def _scan(p):                           # a folder with a magnifier: look through the mod folder again
    p.line((2.5, 5.5), (8, 5.5), (10, 8), (19.5, 8), (19.5, 11))
    p.line((2.5, 5.5), (2.5, 18.5), (11, 18.5))
    p.circle(16, 15.5, 3.6)
    p.line((18.6, 18.1), (21.2, 20.7))


def _update(p):                         # a circling arrow around an up arrow: newer versions
    p.arc(12, 12, 8.5, 200, 520)
    a = math.radians(160)
    p.head(12 + 8.5 * math.cos(a), 12 + 8.5 * math.sin(a), 0.35, -1, length=3.6)
    p.line((12, 16), (12, 8))
    p.line((9, 11), (12, 8), (15, 11))


def _bug(p):                            # crashes
    p.rect(7.5, 8, 9, 12, r=4.5)
    p.line((12, 8), (12, 20))
    p.arc(12, 8, 3, 180, 360)
    for y in (11, 15):
        p.line((7.5, y), (4, y - 1))
        p.line((16.5, y), (20, y - 1))
    p.line((7.5, 18.5), (4.5, 20.5))
    p.line((16.5, 18.5), (19.5, 20.5))


def _broom(p):                          # clean-up
    p.line((19.5, 3.5), (12, 11))
    p.poly((9.5, 9.5), (14.5, 14.5), (10, 21), (3, 14))
    p.line((7, 17.5), (9.5, 15))


def _image(p):                          # a picture
    p.rect(3, 4.5, 18, 15, r=2)
    p.line((5.5, 17), (10, 11.5), (13.5, 15), (15.5, 13), (18.5, 17))
    p.circle(15.5, 8.5, 1.6, fill=True)


def _chain(p):                          # needs other mods
    p.rect(2.5, 8.5, 10, 7, r=3.5)
    p.rect(11.5, 8.5, 10, 7, r=3.5)


def _palette(p):                        # appearance
    p.line((12, 3.5), (8, 3.8), (4.5, 7), (3.5, 12), (5, 17), (9, 20), (13, 20.5), (14.5, 18.5), (13.5, 16),
           (14.5, 14), (18, 14), (20.5, 11.5), (19.5, 7), (16, 4.3), close=True)
    for x, y in ((8, 9), (12, 7), (16.5, 9), (7.5, 14)):
        p.circle(x, y, 1.4, fill=True)


def _key(p):                            # accounts
    p.circle(8, 12, 4.5)
    p.line((12.5, 12), (21, 12))
    p.line((18, 12), (18, 15.5))
    p.line((21, 12), (21, 15))


def _about(p):                          # a crest
    p.line((12, 3), (19.5, 6), (19, 13), (12, 21), (5, 13), (4.5, 6), close=True)
    p.line((12, 8), (12, 15))
    p.line((9, 10.5), (15, 10.5))


ICONS = {
    "search": _search, "download": _download, "upload": _upload, "browse": _globe, "catch": _download,
    "library": _library, "playsets": _playsets, "conflicts": _alert, "alert": _alert, "play": _play,
    "settings": _gear, "help": _help, "info": _info, "moon": _moon, "sun": _sun, "external": _external,
    "refresh": _refresh, "plus": _plus, "minus": _minus, "close": _close, "check": _check, "trash": _trash,
    "folder": _folder, "undo": _undo, "redo": _redo, "up": _up, "down": _down, "left": _left, "right": _right,
    "top": _top, "bottom": _bottom, "sparkle": _sparkle, "pause": _pause, "stop": _stop, "list": _list,
    "grid": _grid, "power": _power, "copy": _copy, "filter_off": _filter_off, "layers": _layers, "star": _star,
    "bars": _bars, "wand": _wand, "steam": _steam, "log": _log, "resume": _play,
    "scan": _scan, "update": _update, "bug": _bug, "broom": _broom, "image": _image, "chain": _chain,
    "retry": _refresh, "crash": _bug, "palette": _palette, "key": _key, "crest": _about,
}


def _rgba(color):
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def draw(name, size=16, color="#000000"):
    """The icon `name` as an RGBA image of size x size, in `color` (#rrggbb)."""
    if Image is None or name not in ICONS:
        return None
    key = (name, size, color)
    with _lock:
        if key in _cache:
            return _cache[key]
    pen = _Pen(size, _rgba(color))
    ICONS[name](pen)
    out = pen.img.resize((size, size), Image.LANCZOS)
    with _lock:
        _cache[key] = out
    return out
