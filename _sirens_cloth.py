"""Sirens living-still driver — cloth (sail + robes) in wind over moonlit water.

Rebuilt from the retired session's scratchpad. Two things were wrong in v5:
the engine only ever applied the FIRST sway layer (so the recipe's flora sway
took it and the sail/robes never ran), and the sway wavelength was frame-scaled,
which makes a small region slide rather than luff. Both fixed in
motion_compositor.py; this drives the fixed engine.
"""
import sys, os, json, numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from region_derive import derive_regions
import living_still as ls

IMG = "inputs/sirens_final.png"
OUT = sys.argv[1] if len(sys.argv) > 1 else "output/Sirens_v6_livingstill.mp4"
SIZE = (1456, 816)
W, H = SIZE

im = np.asarray(Image.open(IMG).convert("RGB").resize(SIZE)).astype(np.float32)
lum = im.mean(2)


def boxed_bright(x0, y0, x1, y1, thresh, grow=3, blur=2.5):
    m = np.zeros((H, W), np.float32)
    m[y0:y1, x0:x1] = (lum[y0:y1, x0:x1] > thresh).astype(np.float32)
    p = Image.fromarray((m * 255).astype(np.uint8))
    p = p.filter(ImageFilter.MaxFilter(grow * 2 + 1)).filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(p).astype(np.float32) / 255.0


# sail: pale canvas between the cliffs; robes: white gowns left foreground
sail = boxed_bright(560, 225, 830, 440, 70)
# The mast is bright enough to fall inside the canvas mask, so the sway bent it
# like a reed. Carve the spar out (found at x=725-734 by column-darkness against
# the canvas) and the timber stays rigid while the cloth moves around it.
sail[:, 718:742] = 0.0
robes = boxed_bright(0, 360, 370, 816, 95)
print("sail cov:", round(float((sail > 0.5).mean()), 4),
      " robes cov:", round(float((robes > 0.5).mean()), 4))

regs = derive_regions(IMG, size=SIZE)
w = regs["open_water"]
w[390:528, 630:820] = 0.0            # hull stays carved out of the water mask
regs["open_water"] = w
regs["sail"] = sail
regs["robes"] = robes
# cloth is animated on purpose — keep it out of any frozen/static accounting
for name in ("foreground", "static"):
    if name in regs:
        regs[name] = np.clip(regs[name] * (1.0 - sail) * (1.0 - robes), 0, 1)

recipe = json.loads(json.dumps(ls.RECIPES["moonlit_shore"]))
recipe["layers"] += [
    # The sail is the loudest cloth in the frame: ~1.5 crests across its own
    # width so the canvas luffs across the panels. Amplitude is down from the
    # v6 pass and the gust is shallow and doubled — v6 held still early and
    # lurched at 17s, and warping smears wherever it lurches.
    {"region": "sail",
     "layer": {"type": "sway", "anchor": "top", "amount": 1.25, "ripple": 1.5,
               "cycles": 2, "cycles_slow": 1, "gust_cycles": 2, "gust_depth": 0.18,
               "slow_ratio": 0.8, "droop": 0.3, "stiffness": 1.8}},
    # Robes: four separate figures under one mask, so the smoothed per-column
    # shoulder line is wrong at the seams between them. Stiff profile parks the
    # travel in the bottom third — hems stir, shoulders hold.
    {"region": "robes",
     "layer": {"type": "sway", "anchor": "top", "amount": 0.85, "ripple": 3.0,
               "cycles": 3, "cycles_slow": 1, "gust_cycles": 2, "gust_depth": 0.15,
               "slow_ratio": 0.5, "droop": 0.25, "stiffness": 3.2}},
]

out, report = ls.render_recipe(IMG, "moonlit_shore", OUT,
                               size=SIZE, guard=True, regions=regs,
                               overrides={"layers": recipe["layers"]})
print("ok:", report["ok"], "failures:", report["failures"])
print({k: round(v, 3) for k, v in report["metrics"].items()})
