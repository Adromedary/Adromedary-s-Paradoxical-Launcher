"""
Square cards for the Browse tab's panel view, drawn as one picture each with Pillow: the mod's preview
filling the square, a dark fade at the bottom with its title, author, age, rating and subscribers, and
two pills on top (game version fit, what you have of it). One picture per card keeps the grid light
(a handful of widgets per page instead of hundreds) and looks the same at every display scale.

Text goes through a small font-fallback chain so Chinese, Japanese, Korean, Cyrillic and symbol
characters in titles are drawn instead of empty boxes.
"""
import os
import threading

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except Exception:                       # pragma: no cover
    Image = None

import glyphs

REGULAR = ["segoeui.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf"]
BOLD = ["segoeuib.ttf", "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arialbd.ttf"]
FALLBACK = ["seguisym.ttf", "msyh.ttc", "msyhbd.ttc", "YuGothM.ttc", "malgun.ttf", "simsun.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

_lock = threading.Lock()
_fonts, _has, _grad, _cache = {}, {}, {}, {}

PILL = {  # kind -> (background, text)
    "ok": ((19, 134, 90, 235), (255, 255, 255, 255)),
    "update": ((37, 99, 217, 240), (255, 255, 255, 255)),
    "dl": ((37, 99, 217, 240), (255, 255, 255, 255)),
    "list": ((255, 255, 255, 235), (37, 99, 217, 255)),
    "missing": ((207, 47, 59, 240), (255, 255, 255, 255)),
    "fit": ((19, 134, 90, 225), (255, 255, 255, 255)),
    "old": ((106, 90, 205, 225), (255, 255, 255, 255)),
    "plain": ((15, 19, 26, 185), (235, 240, 248, 255)),
}


def available():
    return Image is not None


def _font(names, size):
    for n in names:
        key = (n, size)
        if key in _fonts:
            if _fonts[key] is not None:
                return _fonts[key]
            continue
        try:
            _fonts[key] = ImageFont.truetype(n, size)
            return _fonts[key]
        except Exception:
            _fonts[key] = None
    return ImageFont.load_default()


def _fallbacks(size):
    out = []
    for n in FALLBACK:
        key = (n, size)
        if key not in _fonts:
            try:
                _fonts[key] = ImageFont.truetype(n, size)
            except Exception:
                _fonts[key] = None
        if _fonts[key] is not None:
            out.append(_fonts[key])
    return out


def _covers(f, ch):
    """Does font f really draw ch (not its 'missing' box)?"""
    key = (id(f), ch)
    v = _has.get(key)
    if v is None:
        try:
            if f.getlength(ch) <= 0:
                v = ch.isspace()
            else:
                a = _pixels(f, ch)
                v = a != _pixels(f, "\uffff") and a != _pixels(f, "\u0378")
        except Exception:
            v = False
        _has[key] = v
    return v


def _pixels(f, ch):
    key = (id(f), "px", ch)
    v = _has.get(key)
    if v is None:
        n = int(getattr(f, "size", 16)) * 2 + 4
        im = Image.new("L", (n, n), 0)
        ImageDraw.Draw(im).text((2, 2), ch, font=f, fill=255)
        v = _has[key] = im.tobytes()
    return v


def _runs(text, main, size):
    """Split text into (piece, font) runs: the main font where it can, fallbacks elsewhere."""
    runs, cur, cur_f = [], "", None
    fb = None
    for ch in text:
        f = main
        if not ch.isspace() and not _covers(main, ch):
            fb = fb if fb is not None else _fallbacks(size)
            f = next((x for x in fb if _covers(x, ch)), main)
        if f is cur_f:
            cur += ch
        else:
            if cur:
                runs.append((cur, cur_f))
            cur, cur_f = ch, f
    if cur:
        runs.append((cur, cur_f))
    return runs


def _width(text, main, size):
    return sum(f.getlength(t) for t, f in _runs(text, main, size))


def _draw(d, xy, text, main, size, fill):
    x, y = xy
    for t, f in _runs(text, main, size):
        d.text((x, y), t, font=f, fill=fill)
        x += f.getlength(t)
    return x


def _wrap(text, main, size, max_w, max_lines):
    """Word-wrap (character-wrap for scripts without spaces) into max_lines, with an ellipsis if cut."""
    text = " ".join(text.split())
    words, lines, cur = [], [], ""
    for part in text.replace("\n", " ").split(" "):
        words.append(part)
    i = 0
    while i < len(words):
        w = words[i]
        trial = (cur + " " + w).strip() if cur else w
        if _width(trial, main, size) <= max_w:
            cur = trial
            i += 1
            continue
        if not cur:                                  # one long word: cut by characters
            piece = ""
            for ch in w:
                if _width(piece + ch, main, size) > max_w:
                    break
                piece += ch
            piece = piece or w[:1]
            lines.append(piece)
            words[i] = w[len(piece):]
            if not words[i]:
                i += 1
        else:
            lines.append(cur)
            cur = ""
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    used = sum(len(x) for x in lines) + max(0, len(lines) - 1)
    if used < len(text.strip()) and lines:
        last = lines[-1]
        while last and _width(last + "…", main, size) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _gradient(n):
    g = _grad.get(n)
    if g is None:
        g = Image.new("L", (1, n), 0)
        start = int(n * 0.38)
        for y in range(n):
            t = 0 if y < start else (y - start) / max(1, n - start)
            g.putpixel((0, y), int(232 * min(1.0, t ** 1.15)))
        g = _grad[n] = g.resize((n, n))
    return g


def _pill(d, x, y, text, kind, size, icon_name=None, right=False):
    bg, fg = PILL.get(kind, PILL["plain"])
    f = _font(BOLD, size)
    tw = _width(text, f, size)
    ic = int(size * 1.05) if icon_name else 0
    pad = int(size * 0.62)
    w = int(tw + pad * 2 + (ic + int(size * 0.3) if ic else 0))
    h = int(size * 1.75)
    if right:
        x -= w
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=bg)
    tx = x + pad
    if ic:
        im = glyphs.draw(icon_name, ic, "#%02x%02x%02x" % fg[:3])
        if im is not None:
            d._image.alpha_composite(im, (int(tx), int(y + (h - ic) / 2)))
        tx += ic + int(size * 0.3)
    box = f.getbbox("Ag")
    _draw(d, (tx, y + (h - (box[3] - box[1])) / 2 - box[1]), text, f, size, fg)
    return w


def render(item, picture_path, version_text, version_kind, status_text, status_kind, selected, side,
           placeholder=(52, 62, 82), ring=(37, 99, 217), stars=0, votes=0, subs="", meta=""):
    """The card for one Workshop item as an RGBA image of side x side pixels."""
    if Image is None:
        return None
    key = (item.id, picture_path and os.path.getmtime(picture_path) if picture_path and
           os.path.isfile(picture_path) else 0, version_text, status_text, selected, side, ring, meta, subs)
    with _lock:
        if key in _cache:
            return _cache[key]
    S = side
    base = None
    if picture_path and os.path.isfile(picture_path):
        try:
            with Image.open(picture_path) as im:
                base = ImageOps.fit(im.convert("RGB"), (S, S), Image.LANCZOS).convert("RGBA")
        except Exception:
            base = None
    if base is None:
        base = Image.new("RGBA", (S, S), placeholder + (255,))
        g = glyphs.draw("layers" if item.is_collection else "browse", S // 3, "#9aa6bd")
        if g is not None:
            base.alpha_composite(g, ((S - g.size[0]) // 2, int(S * 0.2)))
    shade = Image.new("RGBA", (S, S), (6, 9, 15, 255))
    shade.putalpha(_gradient(S))
    base.alpha_composite(shade)
    d = ImageDraw.Draw(base)
    d._image = base
    m = max(8, S // 22)
    fs = max(10, S // 15)
    # pills on top
    if version_text:
        _pill(d, m, m, version_text, version_kind, max(9, S // 19))
    if status_text:
        _pill(d, S - m, m, status_text, status_kind, max(9, S // 19), right=True)
    # text at the bottom
    tf = _font(BOLD, fs)
    sf = _font(REGULAR, max(9, int(fs * 0.78)))
    title = item.title + (f"  ({item.children})" if item.is_collection and item.children else "")
    lines = _wrap(title, tf, fs, S - 2 * m, 2)
    lh = int(fs * 1.28)
    sh = int(sf.size * 1.35)
    y = S - m - sh * 2 - lh * len(lines) + int(fs * 0.1)
    for ln in lines:
        _draw(d, (m, y), ln, tf, fs, (255, 255, 255, 255))
        y += lh
    y += int(fs * 0.15)
    meta_line = _wrap(meta, sf, sf.size, S - 2 * m, 1)
    if meta_line:
        _draw(d, (m, y), meta_line[0], sf, sf.size, (205, 213, 228, 255))
    y += sh
    # rating: drawn stars, then subscribers
    x = m
    st = max(8, int(sf.size * 0.95))
    if stars > 0:
        for i in range(5):
            g = glyphs.draw("star", st, "#ffcb47" if i < stars else "#6b7385")
            if g is not None:
                base.alpha_composite(g, (int(x), int(y + (sh - st) / 2 - 1)))
            x += st + 2
        x += 6
    elif votes:
        x = _draw(d, (x, y), "few votes  ", sf, sf.size, (170, 180, 198, 255))
    else:
        x = _draw(d, (x, y), "not rated  ", sf, sf.size, (170, 180, 198, 255))
    if subs:
        g = glyphs.draw("download", st, "#cdd5e4")
        if g is not None:
            base.alpha_composite(g, (int(x), int(y + (sh - st) / 2 - 1)))
            x += st + 3
        _draw(d, (x, y), subs, sf, sf.size, (205, 213, 228, 255))
    # rounded corners and the selection ring
    r = max(10, S // 14)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=r, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    if selected:
        w = max(3, S // 60)
        ImageDraw.Draw(out).rounded_rectangle((w // 2, w // 2, S - 1 - w // 2, S - 1 - w // 2), radius=r,
                                              outline=ring + (255,), width=w)
    with _lock:
        if len(_cache) > 400:
            _cache.clear()
        _cache[key] = out
    return out
