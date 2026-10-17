"""
The app's icon, drawn in code so the .exe, the main window and every dialog share it:
a navy heraldic shield with a gold rim, a gold crown, and an arrow dropping into a catch.
"""
import os
import sys

NAVY, NAVY_2 = (22, 34, 66, 255), (33, 52, 98, 255)
GOLD, GOLD_2 = (232, 178, 62, 255), (255, 214, 120, 255)
WHITE, TEAL = (240, 244, 252, 255), (52, 201, 160, 255)


def _shield(w, inset=0):
    """Shield outline as polygon points on a w x w canvas."""
    l, r, t = w * 0.16 + inset, w * 0.84 - inset, w * 0.10 + inset
    side_end = w * 0.52
    pts = [(l, t + w * 0.04), (w * 0.5, t - w * 0.02), (r, t + w * 0.04), (r, side_end)]
    bottom = (w * 0.5, w * 0.93 - inset)
    for i in range(1, 21):                          # right curve down to the point
        k = i / 20
        x = r + (bottom[0] - r) * (k ** 1.6)
        y = side_end + (bottom[1] - side_end) * (1 - (1 - k) ** 2)
        pts.append((x, y))
    for i in range(19, 0, -1):                      # mirror back up the left side
        x, y = pts[3 + i]
        pts.append((w - x, y))
    pts.append((l, side_end))
    return pts


def render(size=256):
    """The icon as an RGBA image of the given size (drawn 4x larger, then smoothed down)."""
    from PIL import Image, ImageDraw            # imported here: without Pillow the app still runs, iconless
    W = 1024
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon(_shield(W), fill=GOLD)                               # gold rim
    d.polygon(_shield(W, inset=34), fill=NAVY)                     # navy field
    d.polygon(_shield(W, inset=34)[:4] + [(W * 0.84 - 34, W * 0.40), (W * 0.16 + 34, W * 0.40)],
              fill=NAVY_2)                                         # lighter chief (top band)
    # crown
    cx, base_y, cw = W * 0.5, W * 0.36, W * 0.40
    x0, x1 = cx - cw / 2, cx + cw / 2
    d.polygon([(x0, base_y), (x0, W * 0.21), (x0 + cw * 0.22, W * 0.29), (cx, W * 0.16),
               (x1 - cw * 0.22, W * 0.29), (x1, W * 0.21), (x1, base_y)], fill=GOLD)
    for px, py in ((x0, W * 0.205), (cx, W * 0.15), (x1, W * 0.205)):
        d.ellipse((px - 26, py - 26, px + 26, py + 26), fill=GOLD_2)
    d.rectangle((x0, base_y - 22, x1, base_y + 10), fill=GOLD_2)
    # arrow dropping into a catch
    d.rectangle((cx - 40, W * 0.44, cx + 40, W * 0.64), fill=WHITE)
    d.polygon([(cx - 115, W * 0.62), (cx + 115, W * 0.62), (cx, W * 0.76)], fill=WHITE)
    d.arc((cx - 175, W * 0.56, cx + 175, W * 0.86), start=20, end=160, fill=TEAL, width=46)
    return img.resize((size, size), Image.LANCZOS)


def write_ico(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    render(256).save(path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    return path


def apply(window, app_dir):
    """Give a Tk/CTk window (or dialog) the app icon. Never raises."""
    try:
        if sys.platform.startswith("win"):
            path = os.path.join(app_dir, ".work", "app.ico")
            if not os.path.isfile(path):
                write_ico(path)
            window.iconbitmap(path)             # also stops customtkinter replacing it with its own
        else:
            from PIL import ImageTk
            img = ImageTk.PhotoImage(render(64))
            window.iconphoto(True, img)
            window._pmc_icon = img              # keep a reference or Tk drops the image
    except Exception:
        pass
