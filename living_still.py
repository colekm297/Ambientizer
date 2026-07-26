"""living_still.py — deterministic recipes for Living Still renders.

The problem this solves: a good living still used to require hand-painting masks
and eyeballing amounts, and every automated attempt shipped something broken.
Here a scene ARCHETYPE names which DERIVED REGION each effect is allowed to touch.
Regions come from region_derive (image-derived, no RNG), so the same recipe works
on any new image of that archetype and the same image always renders identically.

    from living_still import render_recipe
    out, report = render_recipe("scene.png", "night_shore", "out.mp4")
    if not report["ok"]:
        print(report["failures"])

The guardrails below are not hypothetical. Every one of them is a check that
caught a real, shipped-to-the-user defect on this project:

  frozen_regions  the beach shimmered like the sea; the robed figure's head sheared
  strobe          an unmasked twinkle pulsed the campfire on and off 7x per loop
  seam            measured on RAW frames, because H.264 keyframe asymmetry makes an
                  encoded first-vs-last comparison look broken when it is not
  direction       a "seamless" cloud fix turned the drift into a boomerang
  alive           a fix for the above left the scene a static photo
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Optional

import numpy as np
from PIL import Image

from motion_compositor import MotionCompositor
from region_derive import derive_regions

RECIPE_VERSION = 1

# A recipe maps DERIVED REGION NAMES -> layers. "region" is never pixels; it is a
# key into region_derive's output, so the recipe survives a change of image.
# "frozen" regions are asserted static after the render, not merely left out.
RECIPES: dict[str, dict] = {
    "night_shore": {
        "version": RECIPE_VERSION,
        "loop_sec": 16,
        "layers": [
            # stars scintillate, and so do the moonlight glints on open water --
            # but NOT the sand, the cliffs, the fire or a person. Twinkle scales
            # with brightness, so unmasked it hammers the brightest thing in frame.
            {"region": "sky+open_water",
             "layer": {"type": "twinkle", "amount": 0.5, "sparkle": 0.75}},
            # perspective swell: amplitude grows toward the shore, crests travel
            # one direction down the frame and wrap.
            {"region": "open_water",
             "layer": {"type": "wave", "amount": 0.75, "cycles": 3, "density": 1.4,
                       "horizontal": 0.3, "stokes": 0.3, "shear_cap": 0.2,
                       "shore": 0.88, "shore_band": 0.06}},
            # 4-12 Hz emissive flicker + a lagged warm spill. The mask MUST be the
            # 'firelight' halo, not 'fire': _blend_with_mask clips to the mask, so
            # a mask drawn tight to the flame silently deletes the spill.
            {"region": "firelight",
             "layer": {"type": "firelight", "amount": 0.7, "threshold": 150,
                       "spill": 0.6, "spill_radius": 0.5}},
            {"region": "sky",
             "layer": {"type": "cloud_drift", "amount": 0.16, "speed": 1,
                       "mode": "overlay", "tint": "dusk"}},
        ],
        "frozen": ["beach", "foreground"],
    },

    # Night sky over static architecture/terrain: no sea. Any practical lights in
    # the scene (lanterns, windows, a campfire) are found as 'fire' by region
    # derivation and get the real flicker, which is what sells a lit ruin at night.
    "night_ruin": {
        "version": RECIPE_VERSION,
        "loop_sec": 16,
        "layers": [
            {"region": "sky",
             "layer": {"type": "twinkle", "amount": 0.5, "sparkle": 0.75}},
            {"region": "firelight",
             "layer": {"type": "firelight", "amount": 0.6, "threshold": 150,
                       "spill": 0.55, "spill_radius": 0.45}},
            {"region": "sky",
             "layer": {"type": "cloud_drift", "amount": 0.14, "speed": 1,
                       "mode": "overlay", "tint": "dusk"}},
        ],
        "frozen": ["foreground", "beach"],
    },

    # Daylight/dawn landscape: the sky is the only thing alive. Cloud drift is a
    # constant one-direction wrap (never a boomerang), confined to the sky so the
    # terrain cannot slide -- an earlier build dragged a whole mountain sideways.
    "sky_landscape": {
        "version": RECIPE_VERSION,
        "loop_sec": 24,
        "layers": [
            {"region": "sky",
             "layer": {"type": "cloud_drift", "amount": 0.5, "speed": 1,
                       "mode": "slide", "tint": "warm"}},
            {"region": "sky",
             "layer": {"type": "twinkle", "amount": 0.25, "sparkle": 0.6}},
        ],
        "frozen": ["foreground", "beach"],
    },
}


def pick_archetype(regions: dict) -> str:
    """Deterministic archetype choice from the DERIVED REGIONS, not from prose.

    Explicit rules, no model call, so a re-render months later picks the same
    recipe. Order matters: sea wins over lights, lights win over plain sky.
    """
    def cov(name):
        m = regions.get(name)
        return 0.0 if m is None else float((m > 0.5).mean())
    if cov("open_water") > 0.05:
        return "night_shore"
    if cov("fire") > 0.001:
        return "night_ruin"
    return "sky_landscape"


def _resolve_region(regions: dict, spec: str) -> np.ndarray:
    """'sky+open_water' -> union; 'open_water-beach' -> difference."""
    out = None
    for tok in spec.replace("-", " -").replace("+", " +").split():
        neg = tok.startswith("-")
        name = tok.lstrip("+-")
        m = regions[name]
        if out is None:
            out = m.copy() if not neg else 1.0 - m
        else:
            out = np.clip(out * (1.0 - m), 0, 1) if neg else np.clip(out + m, 0, 1)
    return out.astype(np.float32)


def render_recipe(image_path: str, archetype: str, output_path: str,
                  size=(1920, 1080), overrides: Optional[dict] = None,
                  guard: bool = True):
    """Render `image_path` with the named recipe. Returns (output_path, report)."""
    recipe = json.loads(json.dumps(RECIPES[archetype]))   # deep copy
    if overrides:
        recipe.update(overrides)

    regions = derive_regions(image_path, size=size)
    layers, masks = [], {}
    for i, entry in enumerate(recipe["layers"]):
        layers.append(entry["layer"])
        masks[i] = _resolve_region(regions, entry["region"])

    mask_paths, tmp = {}, tempfile.mkdtemp(prefix="ls_masks_")
    for i, m in masks.items():
        p = os.path.join(tmp, f"m{i}.png")
        Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).save(p)
        mask_paths[i] = p

    mc = MotionCompositor()
    out = mc.render(image_path, output_path=output_path, layers=layers,
                    loop_sec=recipe["loop_sec"], fps=24, size=size,
                    layer_masks=mask_paths)

    report = {"ok": True, "failures": [], "metrics": {}}
    if guard:
        report = guard_render(image_path, layers, mask_paths, regions, recipe, size=size)
    return out, report


# ── guardrails ─────────────────────────────────────────────────────────────
# Thresholds are in luminance levels of mean frame-to-frame change, calibrated
# against measurements on this project: a genuinely static region sits at
# 0.01-0.07, and the beach defect that the user caught by eye measured 4.24.
FROZEN_MAX_ENERGY = 0.35      # 5x the worst clean static reading, 12x under the defect
STROBE_MAX_SWING = 0.22       # fraction; the campfire defect was 0.40, stars sit at 0.16
# The fire is ALLOWED to swing -- that is the whole point of the firelight layer --
# but not without limit. A healthy firelight render measures 0.12; the unmasked-twinkle
# defect the user reported measured 0.49. 0.30 sits between them.
FIRE_MAX_SWING = 0.30
SEAM_RATIO_MAX = 2.5          # seam vs median neighbour step, on RAW frames
ALIVE_MIN_ENERGY = 0.15       # below this nothing is moving and the render is dead


def _raw_frames(image_path, layers, mask_paths, loop_sec, size, every=1):
    """Render to lossless PNGs. Encoded video CANNOT be used for the seam check:
    frame 0 is a keyframe and the last frame is not, which reads as a 4x seam on
    a mathematically perfect loop."""
    out = tempfile.mkdtemp(prefix="ls_raw_")
    mc = MotionCompositor()

    def png_out(output_path, W, H, fps, crf):
        return subprocess.Popen(
            [mc.ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-an",
             os.path.join(out, "f_%04d.png")],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    mc._open_ffmpeg = png_out
    mc.render(image_path, output_path=os.path.join(out, "_d.mp4"), layers=layers,
              loop_sec=loop_sec, fps=24, size=size, layer_masks=mask_paths)
    import glob
    return sorted(glob.glob(os.path.join(out, "f_*.png")))


def guard_render(image_path, layers, mask_paths, regions, recipe, size=(1920, 1080)):
    files = _raw_frames(image_path, layers, mask_paths, recipe["loop_sec"], size)
    L = lambda p: np.asarray(Image.open(p)).astype(np.float32).mean(axis=2)
    n = len(files)
    idx = list(range(0, min(24, n)))
    fr = [L(files[i]) for i in idx]
    failures, metrics = [], {}

    def energy(mask, frames):
        w = mask / max(mask.sum(), 1e-6)
        return float(np.mean([np.abs((frames[i + 1] - frames[i]) * w).sum()
                              for i in range(len(frames) - 1)]))

    # 1. frozen regions must not move
    for name in recipe.get("frozen", []):
        e = energy(regions[name], fr)
        metrics[f"frozen.{name}"] = e
        if e > FROZEN_MAX_ENERGY:
            failures.append(f"{name} moved ({e:.3f} > {FROZEN_MAX_ENERGY})")

    # 2. nothing may strobe
    allf = [L(files[i]) for i in range(0, n, max(1, n // 32))]
    for name, m in regions.items():
        if m.sum() < 500:
            continue
        w = m / m.sum()
        v = np.array([float((f * w).sum()) for f in allf])
        swing = float((v.max() - v.min()) / max(v.mean(), 1e-6))
        metrics[f"swing.{name}"] = swing
        if name in ("fire", "firelight"):
            if swing > FIRE_MAX_SWING:
                failures.append(f"{name} strobes ({swing:.2f} > {FIRE_MAX_SWING}) — "
                                f"an unmasked brightness layer is hitting the flame")
        elif swing > STROBE_MAX_SWING and name != "sky":
            failures.append(f"{name} strobes ({swing:.2f} > {STROBE_MAX_SWING})")

    # 3. seam, on RAW frames
    a, b, c = L(files[0]), L(files[1]), L(files[-1])
    step = float(np.abs(b - a).mean())
    seam = float(np.abs(c - a).mean())
    metrics["seam"], metrics["step"] = seam, step
    if seam > SEAM_RATIO_MAX * max(step, 1e-6):
        failures.append(f"loop seam {seam:.3f} vs step {step:.3f}")

    # 4. something must actually move
    live = energy(np.ones_like(fr[0]), fr)
    metrics["alive"] = live
    if live < ALIVE_MIN_ENERGY:
        failures.append(f"nothing moved ({live:.3f})")

    return {"ok": not failures, "failures": failures, "metrics": metrics}
