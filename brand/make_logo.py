"""make_logo.py — The Space of Sound identity.

Three marks, all built on the same observation: an orbit and a sound wave are
the same drawing. Concentric rings read as a planetary system and as sound
radiating from a source at the same time, which is the whole channel in one
shape.

Constraints the design has to survive, not decoration:
  * YouTube crops avatars to a CIRCLE, so every mark is composed inside one.
  * It has to read at 32px, so no fill gradients and no thin hairlines.
  * It sits white-on-black over video, so it is monochrome by construction and
    carries an optional accent that can be dropped without losing the idea.

Everything is drawn at 4x and downsampled — PIL has no antialiased primitives.

    python brand/make_logo.py            # writes all marks + lockups to brand/out
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONTS = HERE.parent / "fonts"
OUT = HERE / "out"
SS = 4  # supersample factor

INK = (255, 255, 255)
ACCENT = (198, 206, 216)   # the silver the thumbnails use
BG = (0, 0, 0)


def _canvas(size):
    return Image.new("RGB", (size * SS, size * SS), BG)


def _down(img, size):
    return img.resize((size, size), Image.LANCZOS)


def _ring(d, cx, cy, r, width, fill, start=None, end=None):
    box = [cx - r, cy - r, cx + r, cy + r]
    if start is None:
        d.ellipse(box, outline=fill, width=width)
    else:
        d.arc(box, start, end, fill=fill, width=width)


# ── Mark 1: ORBIT ─────────────────────────────────────────────────────────
# A source point with rings around it. Unbroken rings read as a bullseye, and
# rings whose gaps CONVERGE read as a wifi icon — so the gaps are all the same
# angular width on the same diagonal, which the eye reads as one body sweeping
# through a system rather than a signal being broadcast at you.
def mark_orbit(size=512, accent=False):
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    c = S / 2
    col = ACCENT if accent else INK
    d.ellipse([c - S * 0.055, c - S * 0.055, c + S * 0.055, c + S * 0.055], fill=col)
    # Gaps centred on the same diagonal (-40 deg), constant width, so their
    # edges form two clean parallel lines instead of a funnel.
    axis, gap = -40, 15
    for i, r in enumerate((0.145, 0.245, 0.345)):
        w = max(3, int(S * (0.022 - i * 0.0022)))
        _ring(d, c, c, S * r, w, col, start=axis + gap, end=axis - gap + 360)
    # One body on the outer path — the thing doing the orbiting.
    a = math.radians(axis + 152)
    br = S * 0.345
    d.ellipse([c + br * math.cos(a) - S * 0.030, c + br * math.sin(a) - S * 0.030,
               c + br * math.cos(a) + S * 0.030, c + br * math.sin(a) + S * 0.030], fill=col)
    return _down(img, size)


# ── Mark 2: HORIZON ───────────────────────────────────────────────────────
# Every scene on this channel is a horizon: dunes, a sea, a mountain ridge,
# a planet's limb. A body rising over a line, with the line rippling into a
# waveform as it leaves the disc — the landscape IS the sound.
def mark_horizon(size=512, accent=False):
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    c = S / 2
    col = ACCENT if accent else INK
    r = S * 0.215
    cy = c - S * 0.045                     # body sits ABOVE the line, rising
    y = cy + r * 0.78
    lw = max(3, int(S * 0.021))

    # Draw the wave across the full width FIRST, then knock a disc-shaped hole
    # in it and stroke the disc on top. Occlusion is what makes the body read as
    # rising OVER a horizon; without it the line runs through the disc and the
    # whole thing looks like a ball on a string.
    wave = Image.new("L", (S, S), 0)
    wd = ImageDraw.Draw(wave)
    for side in (-1, 1):
        pts = []
        for t in range(0, 141):
            f = t / 140.0
            x = c + side * (f * S * 0.46)
            # Fewer, taller cycles. The first pass used a low-amplitude ripple at
            # ~2.6 cycles, which survives neither the 32px crop nor the eye — it
            # read as a bump in a hill. One clear trough either side of the body
            # is legible at any size.
            amp = S * 0.055 * math.sin(min(1.0, f * 1.15) * math.pi) ** 0.9
            pts.append((x, y + amp * math.sin(f * math.pi * 1.55)))
        wd.line(pts, fill=255, width=lw, joint="curve")
    hole = Image.new("L", (S, S), 255)
    ImageDraw.Draw(hole).ellipse([c - r - lw, cy - r - lw, c + r + lw, cy + r + lw], fill=0)
    wave = Image.composite(wave, Image.new("L", (S, S), 0), hole)
    img.paste(Image.new("RGB", (S, S), col), (0, 0), wave)

    d.ellipse([c - r, cy - r, c + r, cy + r], outline=col, width=lw)
    return _down(img, size)


# ── Mark 3: APERTURE ──────────────────────────────────────────────────────
# A waveform bent into a circle: bars radiating from a common centre, their
# lengths following a slow envelope. Reads as an audio meter and as a corona.
def mark_aperture(size=512, accent=False):
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    S = size * SS
    c = S / 2
    col = ACCENT if accent else INK
    n = 60
    r0 = S * 0.155
    d.ellipse([c - r0 * 0.40, c - r0 * 0.40, c + r0 * 0.40, c + r0 * 0.40], fill=col)
    w = max(3, int(S * 0.013))
    for i in range(n):
        a = (i / n) * 2 * math.pi - math.pi / 2
        # Envelope must be periodic over the FULL circle or the first and last
        # bar disagree and the ring looks torn. An odd lobe count with a single
        # dominant term gave a lopsided triangle; two even harmonics keep it
        # symmetric so it reads as a corona, not an accident.
        env = (0.55 + 0.28 * math.sin(i / n * 2 * math.pi * 6)
                    + 0.17 * math.sin(i / n * 2 * math.pi * 12 + 1.1))
        r1 = r0 + S * (0.048 + 0.130 * max(0.0, env))
        d.line([(c + r0 * math.cos(a), c + r0 * math.sin(a)),
                (c + r1 * math.cos(a), c + r1 * math.sin(a))],
               fill=col, width=w)
    return _down(img, size)


MARKS = {"orbit": mark_orbit, "horizon": mark_horizon, "aperture": mark_aperture}


def _font(px):
    for f in ("ArchivoBlack.ttf", "Anton.ttf"):
        p = FONTS / f
        if p.exists():
            return ImageFont.truetype(str(p), px)
    return ImageFont.load_default()


def _tracked(d, xy, text, font, fill, tr):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + tr


def _tracked_w(d, text, font, tr):
    return sum(d.textlength(c, font=font) + tr for c in text) - tr


def lockup(mark_key, W=1920, H=1080, stacked=True, accent_sub=True):
    """Full-frame lockup for the video intro card: mark over wordmark."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    msize = int(H * (0.30 if stacked else 0.24))
    mark = MARKS[mark_key](msize)

    fs = int(H * 0.075)
    font = _font(fs)
    tr = int(fs * 0.16)
    word = "THE SPACE OF SOUND"
    ww = _tracked_w(d, word, font, tr)
    while ww > W * 0.72 and fs > 20:
        fs -= 4
        font = _font(fs); tr = int(fs * 0.16)
        ww = _tracked_w(d, word, font, tr)

    gap = int(H * 0.055)
    total = msize + gap + fs
    top = (H - total) // 2
    img.paste(mark, ((W - msize) // 2, top))
    _tracked(d, ((W - ww) / 2, top + msize + gap), word, font,
             ACCENT if accent_sub else INK, tr)
    return img


def avatar(mark_key, size=800):
    """Circular YouTube avatar — the crop YouTube actually applies."""
    img = Image.new("RGB", (size, size), BG)
    m = MARKS[mark_key](int(size * 0.72))
    img.paste(m, ((size - m.width) // 2, (size - m.height) // 2))
    mask = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * SS, size * SS], fill=255)
    out = Image.new("RGB", (size, size), (18, 18, 18))
    out.paste(img, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


def contact_sheet():
    """One image comparing all three marks at hero size AND at 32px."""
    cell, pad = 380, 40
    W = pad + (cell + pad) * 3
    H = pad + cell + 90 + pad
    sheet = Image.new("RGB", (W, H), (12, 12, 12))
    d = ImageDraw.Draw(sheet)
    lab = _font(26)
    for i, key in enumerate(MARKS):
        x = pad + i * (cell + pad)
        sheet.paste(MARKS[key](cell), (x, pad))
        d.text((x, pad + cell + 16), key.upper(), font=lab, fill=(190, 190, 190))
        tiny = MARKS[key](32)
        sheet.paste(tiny, (x + cell - 40, pad + cell + 44))
    return sheet


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for key in MARKS:
        MARKS[key](1024).save(OUT / f"mark_{key}.png")
        avatar(key).save(OUT / f"avatar_{key}.png")
        lockup(key).save(OUT / f"lockup_{key}.png")
    contact_sheet().save(OUT / "contact_sheet.png")
    print("wrote", OUT)
