"""animate_logo.py — animated Space of Sound logo sting.

The aperture mark, but assembled on screen instead of just fading in. Three
concentric rings of bars counter-rotate, decelerate, and lock into register,
with orbital bodies sweeping the outer paths — the "gears pulling together"
read. The wordmark resolves underneath once the mark has settled.

Motion design notes, since these are the decisions that make it feel deliberate:
  * Every ring uses the SAME ease-out, so they arrive together rather than
    straggling. Different arrival times read as a glitch, not choreography.
  * Adjacent rings spin in opposite directions. Same-direction rings look like
    one rigid object rotating; opposition is what sells interlocking gears.
  * Bar length grows from zero on an offset ramp per ring, so the corona opens
    outward rather than appearing at full size.
  * The letters resolve by tightening tracking, not by fading alone — letter
    spacing collapsing into place is the detail that reads as "designed".

    python brand/animate_logo.py --out brand/out/sting.mp4 --seconds 6
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
FONTS = HERE.parent / "fonts"
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"

# Warm bronze — Greek bronze, firelight, and the copper of the reference sting.
BRONZE = (214, 158, 106)
SILVER = (198, 206, 216)
GOLD = (226, 184, 112)
PALETTES = {"bronze": BRONZE, "silver": SILVER, "gold": GOLD}

SS = 2  # supersample


def _ease_out(x, p=3.0):
    """Decelerate hard at the end — the 'lock into place' feel."""
    return 1.0 - (1.0 - max(0.0, min(1.0, x))) ** p


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


# Three rings of bars: (count, inner radius, bar length, spin turns, direction)
# Radii must leave a GAP after each ring's longest bar, or the bands overlap
# into one dense mass and the counter-rotation becomes invisible — the thing
# that makes it read as interlocking gears is the clear space between them.
# Ring n's reach is r0 + bar_len * 1.3; the next r0 sits above that.
RINGS = (
    (30, 0.095, 0.042, 0.75, +1),   # reach 0.150
    (44, 0.170, 0.048, 0.55, -1),   # reach 0.232
    (60, 0.250, 0.055, 0.40, +1),   # reach 0.322
)


def frame(t, W=1920, H=1080, color=BRONZE, word="THE SPACE OF SOUND"):
    """One frame at normalized time t in [0,1]."""
    S = 2
    img = Image.new("RGB", (W * S, H * S), (0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = W * S / 2, H * S / 2 - H * S * 0.06
    R = H * S

    settle = _ease_out(min(1.0, t / 0.62), 3.2)      # rings lock by t=0.62
    glow = Image.new("RGB", (W * S, H * S), (0, 0, 0))
    gd = ImageDraw.Draw(glow)

    for ri, (n, r0f, blf, turns, direction) in enumerate(RINGS):
        # Each ring opens on its own ramp but lands on the same beat.
        open_t = _ease_out(min(1.0, max(0.0, (t - ri * 0.06) / 0.56)), 2.4)
        if open_t <= 0.001:
            continue
        spin = direction * turns * 2 * math.pi * (1.0 - settle)
        r0 = R * r0f
        bl = R * blf * open_t
        w = max(2, int(R * 0.0042))
        for i in range(n):
            a = (i / n) * 2 * math.pi + spin
            env = (0.55 + 0.28 * math.sin(i / n * 2 * math.pi * 6)
                        + 0.17 * math.sin(i / n * 2 * math.pi * 12 + 1.1))
            r1 = r0 + bl * (0.45 + 0.85 * max(0.0, env))
            p0 = (cx + r0 * math.cos(a), cy + r0 * math.sin(a))
            p1 = (cx + r1 * math.cos(a), cy + r1 * math.sin(a))
            d.line([p0, p1], fill=color, width=w)
            gd.line([p0, p1], fill=color, width=w)

    # Core dot pops on the lock.
    cr = R * 0.026 * _ease_out(min(1.0, max(0.0, (t - 0.28) / 0.34)), 2.0)
    if cr > 1:
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(255, 246, 236))
        gd.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=color)

    # Orbital bodies sweeping the outer path — the reference's signature move.
    for k, (orf, turns, direction) in enumerate(((0.352, 0.9, -1), (0.400, 0.7, +1))):
        op = _ease_out(min(1.0, max(0.0, (t - 0.10) / 0.60)), 2.6)
        if op <= 0.01:
            continue
        a = direction * turns * 2 * math.pi * (1.0 - settle) + k * 2.3
        orr = R * orf
        bx, by = cx + orr * math.cos(a), cy + orr * math.sin(a)
        rr = R * 0.010
        d.ellipse([bx - rr, by - rr, bx + rr, by + rr], outline=color,
                  width=max(2, int(R * 0.0032)))
        _ring_r = orr
        d.arc([cx - _ring_r, cy - _ring_r, cx + _ring_r, cy + _ring_r],
              0, 360, fill=tuple(int(c * 0.62) for c in color),
              width=max(1, int(R * 0.0016)))

    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(int(R * 0.010))), 0.42)
    img = Image.blend(img, glow, 0.0)
    d = ImageDraw.Draw(img)

    # Wordmark: tracking collapses inward as it fades up.
    wt = _ease_out(min(1.0, max(0.0, (t - 0.46) / 0.42)), 2.2)
    if wt > 0.01:
        fs = int(H * S * 0.058)
        font = _font(fs)
        tr = int(fs * (0.62 - 0.46 * wt))     # wide -> settled
        ww = _tracked_w(d, word, font, tr)
        while ww > W * S * 0.78 and fs > 20:
            fs -= 4
            font = _font(fs); tr = int(fs * (0.62 - 0.46 * wt))
            ww = _tracked_w(d, word, font, tr)
        shade = tuple(int(c * wt) for c in (236, 240, 246))
        _tracked(d, ((W * S - ww) / 2, cy + R * 0.30), word, font, shade, tr)

    return img.resize((W, H), Image.LANCZOS)


def render(out_path, seconds=6.0, fps=30, W=1920, H=1080, color=BRONZE, hold=1.4):
    tmp = Path(tempfile.mkdtemp(prefix="sting_"))
    try:
        n_anim = int((seconds - hold) * fps)
        n_hold = int(hold * fps)
        for i in range(n_anim):
            frame(i / max(1, n_anim - 1), W, H, color).save(tmp / f"f_{i:04d}.png")
        last = frame(1.0, W, H, color)
        for j in range(n_hold):
            last.save(tmp / f"f_{n_anim + j:04d}.png")
        subprocess.run([FFMPEG, "-y", "-framerate", str(fps), "-i", str(tmp / "f_%04d.png"),
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                        "-pix_fmt", "yuv420p", str(out_path)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(out_path)
    finally:
        for p in tmp.glob("*"):
            try: p.unlink()
            except OSError: pass
        try: tmp.rmdir()
        except OSError: pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out" / "sting.mp4"))
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--color", default="bronze", choices=list(PALETTES))
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    print(render(a.out, seconds=a.seconds, fps=a.fps, color=PALETTES[a.color]))
