"""
Pictures for the lists: role badges (a coloured tile with a symbol per kind of mod), mod thumbnails
(the mod's own thumbnail.png, or its Steam Workshop preview, cached), and the small row images that
combine the two. Everything is drawn with Pillow; without Pillow the app shows text only.
"""
import os
import threading

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except Exception:                       # pragma: no cover
    Image = None

FONT_CANDIDATES = ["seguisym.ttf", "segoeui.ttf", "arialuni.ttf", "DejaVuSans.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
_fonts, _lock = {}, threading.Lock()
_badges, _thumbs = {}, {}


def available():
    return Image is not None


def _font(name, size):
    key = (name, size)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(name, size)
        except Exception:
            _fonts[key] = None
    return _fonts[key]


def _has_glyph(font, ch):
    """Does this font really draw `ch` (and not its 'missing' box)?"""
    try:
        box = font.getbbox(ch)
        if not box or box[2] - box[0] <= 0:
            return False
        def render(c):
            im = Image.new("L", (int(font.size * 2), int(font.size * 2)), 0)
            ImageDraw.Draw(im).text((2, 2), c, font=font, fill=255)
            return im.tobytes()
        return render(ch) != render("￿")
    except Exception:
        return False


def _glyph_font(text, size):
    for name in FONT_CANDIDATES:
        f = _font(name, size)
        if f is not None and all(_has_glyph(f, ch) for ch in text if not ch.isspace()):
            return f
    return None


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def badge(role, size=18):
    """A rounded tile in the role's colour with its symbol in white."""
    if Image is None:
        return None
    key = (role.id, size)
    with _lock:
        if key in _badges:
            return _badges[key]
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.26), fill=_hex(role.color))
    text = role.glyph
    f = _glyph_font(text, int(S * (0.7 if len(text) == 1 else 0.46)))
    if f is None:
        text = role.name[:1]
        f = _glyph_font(text, int(S * 0.62)) or ImageFont.load_default()
    box = d.textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((S - w) / 2 - box[0], (S - h) / 2 - box[1]), text, font=f, fill=(255, 255, 255, 255))
    out = img.resize((size, size), Image.LANCZOS)
    with _lock:
        _badges[key] = out
    return out


# ------------------------------------------------------------------ thumbnails
def thumb_file(mod, wid="", cache_dir=""):
    """The best picture for a mod: its own thumbnail (descriptor 'picture' or thumbnail.png/jpg in its
    folder), else a cached Workshop preview."""
    folder = mod.folder if mod.folder and os.path.isdir(mod.folder) else ""
    names = []
    pic = getattr(mod, "picture", "") or ""
    if pic:
        names.append(pic)
    names += ["thumbnail.png", "thumbnail.jpg", "thumbnail.jpeg", "Thumbnail.png"]
    if folder:
        for n in names:
            p = os.path.join(folder, n)
            if os.path.isfile(p) and load_thumb(p, 16) is not None:
                return p
    if wid and cache_dir:
        for ext in (".jpg", ".png"):
            p = os.path.join(cache_dir, wid + ext)
            if os.path.isfile(p) and os.path.getsize(p) > 0 and load_thumb(p, 16) is not None:
                return p
    return ""


def load_thumb(path, size):
    """A square, centre-cropped thumbnail (cached)."""
    if Image is None or not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime, size)
    with _lock:
        if key in _thumbs:
            return _thumbs[key]
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im = ImageOps.fit(im, (size, size), Image.LANCZOS)
    except Exception:
        im = None
    with _lock:
        if len(_thumbs) > 1500:
            _thumbs.clear()
        _thumbs[key] = im
    return im


def rounded(im, radius):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.size[0] - 1, im.size[1] - 1), radius=radius, fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def placeholder(role, size):
    """No picture: a soft tile in the role's colour with its symbol."""
    S = size * 2
    base = Image.new("RGBA", (S, S), _hex(role.color)[:3] + (60,))
    b = badge(role, int(S * 0.55))
    if b:
        base.alpha_composite(b, ((S - b.size[0]) // 2, (S - b.size[1]) // 2))
    return base.resize((size, size), Image.LANCZOS)


def row_image(thumb_path, role, h=32, badge_size=16, gap=4):
    """Thumbnail + role badge side by side, for a list row."""
    if Image is None:
        return None
    t = load_thumb(thumb_path, h) if thumb_path else None
    t = rounded(t, 6) if t is not None else rounded(placeholder(role, h), 6)
    img = Image.new("RGBA", (h + gap + badge_size, h), (0, 0, 0, 0))
    img.alpha_composite(t, (0, 0))
    b = badge(role, badge_size)
    if b:
        img.alpha_composite(b, (h + gap, (h - badge_size) // 2))
    return img


def hero(thumb_path, role, width=320):
    """Big picture for a detail pane (wide, rounded)."""
    if Image is None:
        return None
    t = load_thumb(thumb_path, width) if thumb_path else None
    if t is None:
        t = placeholder(role, width)
    return rounded(t, 14)


def fetch_previews(net, wanted, cache_dir, done=None):
    """Download Workshop preview pictures for mods without their own thumbnail.
    wanted: {workshop id: preview url}. Runs in the caller's thread; never raises."""
    os.makedirs(cache_dir, exist_ok=True)
    got = 0
    for wid, url in wanted.items():
        if not url:
            continue
        dest = os.path.join(cache_dir, wid + ".jpg")
        if os.path.isfile(dest):
            continue
        try:
            r = net.get(url, timeout=30, retries=1)
            if r.status == 200 and r.content:
                tmp = dest + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(r.content)
                if Image is not None:
                    with Image.open(tmp) as im:
                        im = im.convert("RGB")
                        im.thumbnail((512, 512))
                        im.save(dest, "JPEG", quality=88)
                    os.remove(tmp)
                else:
                    os.replace(tmp, dest)
                got += 1
        except Exception:
            pass
    if done:
        done(got)
    return got
