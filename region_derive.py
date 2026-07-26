"""
region_derive.py — deterministic, image-derived REGION masks for motion layers.

Why this exists: layers were being scoped by hand-painted PNGs, and the one
automatic source (semantic sky/water from segmenter.py) is wrong in two ways on
beach scenes -- the "water" class swallows the wet sand AND any person standing
at the waterline. The result is that the beach shimmers like the sea.

This module takes the semantic sky/water masks as a starting point and derives a
full set of named regions from the image itself. Nothing here is tuned to one
picture: every threshold is either an Otsu split computed on this image's own
histogram or a fraction of the frame size.

    from region_derive import derive_regions
    regions = derive_regions("scene.png", size=(1920, 1080))
    regions["open_water"]   # float32 (H, W) in [0, 1]

Returned keys
    sky         semantic sky
    open_water  the SEA ONLY (semantic water minus beach minus foreground)
    beach       sand / shore, so it can be explicitly frozen
    fire        self-luminous warm blobs
    firelight   dilated halo covering the rock + sand the fire lights
    foreground  subjects that must never move (a figure at the waterline)
    static      everything that must stay pixel-frozen

All masks are float32 (H, W) in [0, 1] and feathered, so no effect boundary is a
hard cut. The derivation is pure numpy/scipy with no RNG anywhere -- the same
image in gives byte-identical masks out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import (
    binary_closing,
    binary_dilation,
    binary_fill_holes,
    binary_opening,
    gaussian_filter,
    label,
    median_filter,
    uniform_filter,
)

REGION_NAMES = (
    "sky",
    "open_water",
    "beach",
    "fire",
    "firelight",
    "foreground",
    "static",
)

_EPS = 1e-3


# ── generic helpers ────────────────────────────────────────────────────────
def _otsu(values: np.ndarray, lo: float, hi: float, bins: int = 256) -> float:
    """Otsu's two-class threshold on a fixed [lo, hi] histogram.

    Fixed bin edges (rather than data-driven ones) keep the result bit-stable
    for a given image and independent of sample ordering.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    if v.size == 0:
        return 0.5 * (lo + hi)
    hist, _ = np.histogram(v, bins=bins, range=(lo, hi))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return 0.5 * (lo + hi)
    p = hist / total
    centers = lo + (np.arange(bins, dtype=np.float64) + 0.5) * (hi - lo) / bins
    w0 = np.cumsum(p)
    w1 = 1.0 - w0
    m0 = np.cumsum(p * centers)
    mt = m0[-1]
    denom = np.maximum(w0 * w1, 1e-12)
    between = (mt * w0 - m0) ** 2 / denom
    between[w0 <= 0] = -1.0
    between[w1 <= 0] = -1.0
    return float(centers[int(np.argmax(between))])


def _largest_components(mask: np.ndarray, min_area: int, keep_ratio: float = 0.25
                        ) -> np.ndarray:
    """Keep connected components that are at least `keep_ratio` of the biggest one
    and at least `min_area` pixels. Kills speckle (e.g. warm stars) without a
    magic per-image size."""
    lab, n = label(mask)
    if n == 0:
        return np.zeros_like(mask, dtype=bool)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    biggest = int(sizes.max())
    keep = np.nonzero((sizes >= max(min_area, int(biggest * keep_ratio))) & (sizes > 0))[0]
    return np.isin(lab, keep)


def _touching_components(mask: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """All connected components of `mask` that contain at least one `seed` pixel."""
    lab, n = label(mask)
    if n == 0:
        return np.zeros_like(mask, dtype=bool)
    ids = np.unique(lab[seed & mask])
    ids = ids[ids > 0]
    if ids.size == 0:
        return np.zeros_like(mask, dtype=bool)
    return np.isin(lab, ids)


def _feather(mask_bool: np.ndarray, sigma: float) -> np.ndarray:
    """Binary → feathered float32 [0, 1]. Blur then clip (no max-renormalise, which
    would blow small masks up to full strength)."""
    m = gaussian_filter(mask_bool.astype(np.float32), sigma=float(sigma), mode="nearest")
    return np.clip(m, 0.0, 1.0).astype(np.float32)


def _odd(n: int) -> int:
    n = int(max(1, n))
    return n if n % 2 == 1 else n + 1


# ── image features ─────────────────────────────────────────────────────────
def _features(rgb: np.ndarray) -> dict:
    """Illumination-normalised colour + texture features.

    blue_rel / warm_rel divide by luminance so a dark patch of sea and a
    moonlit-bright patch of sea land in the same place. That is what makes a
    single global threshold legitimate instead of a per-row fudge.
    """
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    lum = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)
    denom = np.maximum(lum, _EPS)
    blue_rel = ((b - 0.5 * (r + g)) / denom).astype(np.float32)
    warm_rel = ((r - b) / denom).astype(np.float32)
    H_, W_ = rgb.shape[0], rgb.shape[1]
    win = _odd(max(5, int(round(min(H_, W_) / 120.0))))
    m1 = uniform_filter(lum, win)
    m2 = uniform_filter(lum * lum, win)
    tex = (np.sqrt(np.maximum(m2 - m1 * m1, 0.0)) / np.maximum(m1, _EPS)).astype(np.float32)
    # wave energy: local mean of band-pass detail. Breaking surf is the most
    # textured surface in a beach frame; dry sand is the least. This is the term
    # that finds the true waterline, which colour alone cannot.
    detail = np.abs(lum - gaussian_filter(lum, sigma=max(2.0, min(H_, W_) / 270.0),
                                          mode="nearest"))
    wave = uniform_filter(detail, size=_odd(int(round(0.02 * min(H_, W_))))).astype(np.float32)
    # self-luminous excess: how much brighter than the broad local average
    excess = (lum - gaussian_filter(lum, sigma=max(rgb.shape) / 24.0, mode="nearest"))
    return dict(lum=lum, blue_rel=blue_rel, warm_rel=warm_rel, tex=tex, wave=wave,
                rb=(r - b).astype(np.float32), excess=excess.astype(np.float32))


# ── semantic segmentation (reused, not reinvented) ─────────────────────────
def default_seg_provider(image_path: str):
    """(sky_png, water_png) from the existing pipeline.

    Prefers MotionCompositor._ensure_seg_masks so the cache and the subprocess
    invocation stay in exactly one place; falls back to the cache filenames it
    writes if the compositor can't be imported.
    """
    src = Path(image_path)
    sky_p = src.with_name(src.stem + "_seg_sky.png")
    water_p = src.with_name(src.stem + "_seg_water.png")
    if sky_p.exists() and water_p.exists():
        return str(sky_p), str(water_p)
    try:
        from motion_compositor import MotionCompositor  # noqa: WPS433
        return MotionCompositor()._ensure_seg_masks(str(image_path))
    except Exception:
        return (str(sky_p) if sky_p.exists() else None,
                str(water_p) if water_p.exists() else None)


def _load_mask(path, W: int, H: int) -> Optional[np.ndarray]:
    """Same contract as MotionCompositor._load_region_mask."""
    if not path or not Path(path).exists():
        return None
    m = np.asarray(Image.open(path).convert("L").resize((W, H), Image.BILINEAR),
                   dtype=np.float32) / 255.0
    return m if float(m.max()) > 0.02 else None


# ── fire ───────────────────────────────────────────────────────────────────
def _derive_fire(f: dict, W: int, H: int):
    """Self-luminous warm blobs.

    A fire is warm AND bright AND locally the brightest thing around. Warm-and-
    bright alone also fires on orange stars and on the rock the fire is lighting,
    so the split runs in three image-derived stages:
      1. warm       = Otsu over warm_rel across the whole frame (plus r > b)
      2. bright     = Otsu over lum restricted to those warm pixels
      3. self-lit   = Otsu over the local brightness excess, which is what tells a
                      SOURCE apart from the surface it is lighting
    Components smaller than a quarter of the biggest are then dropped, which is
    what removes the stars (thousands of ~10 px warm specks).
    """
    warm_rel, lum, excess = f["warm_rel"], f["lum"], f["excess"]
    # "warm" is relative to the frame's own colour balance -- a moonlit night
    # scene is globally blue, so an absolute R>B cut alone would find nothing.
    # Otsu over warm_rel finds the scene's warm/cool split; the extra r>b term
    # keeps the class physically warm when the scene is already warm overall.
    t_warm = max(_otsu(warm_rel, -1.5, 1.5), float(np.median(warm_rel)))
    warm_px = (warm_rel > t_warm) & (f["rb"] > 0.0)
    if warm_px.sum() < 64:
        empty = np.zeros((H, W), dtype=bool)
        return empty, empty, dict(t_warm=t_warm, t_lum=None, t_exc=None, area=0)
    t_lum = _otsu(lum[warm_px], 0.0, 1.0)
    # a fire core must also out-shine its own neighbourhood, else the wall the
    # fire is lighting qualifies too (it is warm and bright, just not a source)
    t_exc = _otsu(excess[warm_px], -0.5, 0.7)
    core = warm_px & (lum > t_lum) & (excess > t_exc)
    core = binary_opening(core, structure=np.ones((3, 3), bool))
    min_area = max(64, int(0.00015 * W * H))
    fire = _largest_components(core, min_area=min_area, keep_ratio=0.25)
    fire = binary_closing(fire, structure=np.ones((9, 9), bool))
    fire = binary_fill_holes(fire)
    # A flame is a SOURCE, so it is small. When the "fire" class comes back as a
    # large share of the frame the scene is just warmly lit (a sunlit desert, a
    # golden-hour sky) and there is no source to flicker -- return nothing rather
    # than set the whole landscape twitching.
    max_frac = 0.03
    rejected = float(fire.mean()) > max_frac
    if rejected:
        fire = np.zeros((H, W), dtype=bool)
    info = dict(t_warm=float(t_warm), t_lum=float(t_lum), t_exc=float(t_exc),
                area=int(fire.sum()), rejected_as_ambient_warmth=rejected,
                max_frac=max_frac)
    return fire, warm_px, info


def _derive_firelight(fire: np.ndarray, f: dict, W: int, H: int) -> np.ndarray:
    """Halo over the surfaces the fire actually lights.

    Not a plain circle: the blurred fire gives the falloff, and it is gated by
    where the image is genuinely warmer than the frame's own warm baseline. So
    the halo hugs the lit cave wall and the lit sand and stops at the cold sea.
    """
    if not fire.any():
        return np.zeros((H, W), dtype=np.float32)
    area = float(fire.sum())
    radius = float(np.sqrt(area / np.pi))
    sigma = float(np.clip(radius * 1.6, 0.02 * max(W, H), 0.16 * max(W, H)))
    falloff = gaussian_filter(fire.astype(np.float32), sigma=sigma, mode="nearest")
    peak = float(falloff.max())
    if peak <= 0:
        return np.zeros((H, W), dtype=np.float32)
    falloff = np.clip(falloff / peak * 3.0, 0.0, 1.0)  # broaden the plateau
    warm_rel = f["warm_rel"]
    base = float(np.median(warm_rel))
    spread = float(np.percentile(warm_rel, 90) - base) or 1.0
    lit = np.clip((warm_rel - base) / max(spread, 1e-3), 0.0, 1.0)
    lit = gaussian_filter(lit, sigma=max(2.0, min(W, H) / 300.0), mode="nearest")
    halo = np.clip(falloff * (0.35 + 0.65 * lit), 0.0, 1.0)
    halo = np.maximum(halo, fire.astype(np.float32))
    return halo.astype(np.float32)


# ── sea / beach split: three candidate methods ─────────────────────────────
def _solidify(raw: np.ndarray, band: np.ndarray, W: int, H: int) -> np.ndarray:
    """Turn a speckled per-pixel classification into one solid region.

    Open sea is shot through with moonlight glints and dark wave troughs, so the
    raw per-pixel test comes back as lace. A local-majority vote (box filter, then
    >= 0.5) closes it without moving the outer boundary, which is the only part
    that matters here -- the boundary IS the waterline. Then keep only what hangs
    off the top of the water band, which drops isolated bright sand patches.
    """
    vh = _odd(int(round(0.035 * H)))
    vw = _odd(int(round(0.035 * W)))
    prob = uniform_filter(raw.astype(np.float32), size=(vh, vw), mode="constant", cval=0.0)
    solid = (prob >= 0.5) & band
    solid = binary_fill_holes(solid)
    rows = np.nonzero(band.any(axis=1))[0]
    if rows.size:
        seed = np.zeros((H, W), dtype=bool)
        seed[rows[0]:rows[0] + max(3, int(0.02 * H)), :] = True
        anchored = _touching_components(solid, seed & band)
        if anchored.sum() > 0.2 * max(solid.sum(), 1):
            solid = anchored
    return solid


def _raw_shore(sea_solid: np.ndarray, W: int, H: int) -> np.ndarray:
    """Deepest sea row in each column; NaN where the column has no sea at all."""
    line = np.full(W, np.nan, dtype=np.float64)
    for x in range(W):
        idx = np.nonzero(sea_solid[:, x])[0]
        if idx.size:
            line[x] = float(idx.max())
    return line


def _waterline(sea_solid: np.ndarray, W: int, H: int) -> np.ndarray:
    """Deepest sea row per column, robust-median-smoothed across x.

    The median window is ~9% of the frame width. A person is a couple of percent
    wide, so the notch they cut in the raw line is a minority inside every window
    it touches and the median steps straight over it. That is what recovers the
    TRUE waterline from a scene with someone standing in it -- and it is also how
    the person gets found, as the gap between raw and smoothed.
    """
    line = _raw_shore(sea_solid, W, H)
    known = ~np.isnan(line)
    if not known.any():
        return np.full(W, H * 0.75, dtype=np.float64)
    idx_all = np.arange(W, dtype=np.float64)
    line = np.interp(idx_all, idx_all[known], line[known])
    line = median_filter(line, size=_odd(int(0.09 * W)), mode="nearest")
    line = gaussian_filter(line, sigma=max(2.0, W / 240.0), mode="nearest")
    return line


def sea_split_chroma(f: dict, band: np.ndarray, W: int, H: int):
    """METHOD A — chromatic split.

    Sea (including foam) keeps a blue cast; sand is near-neutral or warm. Otsu
    the illumination-normalised blue chroma over the semantic-water band only.
    Normalising by luminance is what lets one global threshold hold from the dark
    horizon down to the bright surf.
    """
    t = _otsu(f["blue_rel"][band], -1.0, 1.0)
    raw = band & (f["blue_rel"] > t)
    return raw, dict(threshold=float(t), feature="blue_rel")


def sea_split_luminance(f: dict, band: np.ndarray, W: int, H: int):
    """METHOD B — luminance split.

    Moonlit sand is pale and bright, open sea is dark. Otsu luminance over the
    band and call the dark class sea.
    """
    t = _otsu(f["lum"][band], 0.0, 1.0)
    raw = band & (f["lum"] < t)
    return raw, dict(threshold=float(t), feature="lum")


def sea_split_chroma_texture(f: dict, band: np.ndarray, W: int, H: int):
    """METHOD C — chroma OR wave texture. This is the one that is correct.

    Chroma alone puts the waterline at the deep-water/foam edge, because breaking
    surf is white and reads as sand. But surf is the most *textured* thing in the
    frame and dry sand is the smoothest, so a wave-energy term picks up exactly
    the band chroma loses. The union is the right operator: water is water if it
    is blue OR if it is churning. Sand is neither.

    (The hazy horizon is smooth and needs the chroma term; the swash zone is pale
    and needs the texture term. Neither feature covers both.)
    """
    t_c = _otsu(f["blue_rel"][band], -1.0, 1.0)
    wave = f["wave"]
    hi = float(np.percentile(wave[band], 99.5))
    t_w = _otsu(wave[band], 0.0, max(hi, 1e-4))
    raw = band & ((f["blue_rel"] > t_c) | (wave > t_w))
    return raw, dict(threshold=float(t_c), feature="blue_rel|wave",
                     threshold_wave=float(t_w))


SEA_SPLIT_METHODS = {
    "chroma": sea_split_chroma,
    "luminance": sea_split_luminance,
    "chroma_texture": sea_split_chroma_texture,
}

# Measured on output/a38b5c83_custom_image.png (1920x1080). "accuracy" is the
# balanced mean of (open_water over four hand-verified sea patches) and
# (1 - open_water over four hand-verified sand patches); the probes score the
# methods, they are not used by them. "waterline@figure" is the derived shore row
# in the figure's columns -- the true foam edge there, read off a 4x crop, is 971.
MEASURED_METHODS = {
    "chroma":         dict(accuracy=0.8740, waterline_at_figure=796.6,
                           note="misses the swash: white surf reads as sand"),
    "luminance":      dict(accuracy=0.8699, waterline_at_figure=794.3,
                           note="same failure, plus it loses bright foam entirely"),
    "chroma_texture": dict(accuracy=0.9196, waterline_at_figure=978.2,
                           note="WINNER -- lands within 7 px of the real shore"),
}


# ── foreground subjects ────────────────────────────────────────────────────
def _derive_foreground(sea_solid, waterline, f, W, H):
    """Subjects standing in / at the water -- found from the sea's own outline.

    A person at the waterline INTERRUPTS the sea: in their columns the deepest sea
    pixel jumps upward, while the median-smoothed waterline steps straight over
    them. The difference between the two lines -- the notch -- is a pure geometric
    detector for "something is standing here". It needs no colour model, no size
    prior, and no idea what the subject is.

    The notch only localises the subject, though; it marks whatever part of them
    broke the sea line. The full silhouette comes from a colour region-grow seeded
    inside the notch, and the grow tolerance is itself derived: expand until the
    distance would start admitting the water around the subject (5th percentile of
    the seed-distance over local sea pixels). So the subject stops exactly where
    the sea begins.

    Nothing here names a coordinate. Every gate is a fraction of the frame.
    """
    raw_shore = _raw_shore(sea_solid, W, H)
    notch = np.where(np.isnan(raw_shore), 0.0, waterline - raw_shore)
    lum, blue_rel, warm_rel = f["lum"], f["blue_rel"], f["warm_rel"]
    scale = np.array([0.10, 0.15, 0.22], dtype=np.float64)

    min_notch = 0.02 * H
    min_run = max(4, int(0.004 * W))
    cols = np.nonzero(notch > min_notch)[0]
    fg = np.zeros((H, W), dtype=bool)
    picks = []
    if cols.size == 0:
        return fg, picks
    runs = [r for r in np.split(cols, np.nonzero(np.diff(cols) > 4)[0] + 1)
            if r.size >= min_run]

    for r in runs:
        x0, x1 = int(r.min()), int(r.max())
        seed = np.zeros((H, W), dtype=bool)
        for x in r:
            top = int(raw_shore[x])
            bot = int(round(waterline[x]))
            if bot > top:
                seed[top:bot + 1, x] = True
        if seed.sum() < 50:
            continue
        # a subject STANDS IN the water: at the height where it breaks the sea
        # line there must be sea on both sides of it. A dip in the shore where the
        # sea simply ends (a cove corner, the cave mouth) has water on one side
        # only, and this is what rejects it.
        y_probe = int(np.nanmin(raw_shore[r]))
        reach = max(20, int(0.05 * W))
        left = sea_solid[y_probe, max(0, x0 - reach):x0]
        right = sea_solid[y_probe, x1 + 1:min(W, x1 + 1 + reach)]
        if not (left.any() and right.any()):
            picks.append(dict(run=(x0, x1), notch=round(float(notch[r].max()), 1),
                              kept=False, rejected_for=["not flanked by water"]))
            continue
        ref = np.array([np.median(lum[seed]), np.median(blue_rel[seed]),
                        np.median(warm_rel[seed])], dtype=np.float64)
        nh = int(notch[r].max())
        pad = max(10, int(1.5 * (x1 - x0 + 1)))
        bx0, bx1 = max(0, x0 - pad), min(W, x1 + 1 + pad)
        by0 = max(0, int(waterline[r].min()) - 3 * nh)
        by1 = min(H, int(waterline[r].max()) + 2 * nh)
        sub = np.stack([lum[by0:by1, bx0:bx1], blue_rel[by0:by1, bx0:bx1],
                        warm_rel[by0:by1, bx0:bx1]], axis=-1).astype(np.float64)
        dist = np.sqrt((((sub - ref) / scale) ** 2).sum(-1))
        sea_loc = sea_solid[by0:by1, bx0:bx1]
        if sea_loc.sum() > 50:
            tol = float(np.percentile(dist[sea_loc], 5))
        else:
            tol = _otsu(dist, 0.0, float(np.percentile(dist, 99)))
        near = binary_closing(dist < tol, structure=np.ones((9, 9), bool))
        lab, n = label(near)
        ids = np.unique(lab[seed[by0:by1, bx0:bx1] & near])
        ids = ids[ids > 0]
        blob = np.zeros((H, W), dtype=bool)
        if ids.size:
            blob[by0:by1, bx0:bx1] = np.isin(lab, ids)
        blob = binary_fill_holes(blob)
        if not blob.any():
            continue
        # small margin so a shimmer never creeps up to the subject's edge; sized
        # from the subject itself rather than a pixel constant
        ys, xs = np.nonzero(blob)
        span = min(int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        blob = binary_dilation(blob, structure=np.ones((3, 3), bool),
                               iterations=max(2, int(round(0.08 * span))))
        ys, xs = np.nonzero(blob)
        by, bY, bx, bX = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
        w, h = bX - bx + 1, bY - by + 1
        reasons = []
        if blob.sum() < max(64, int(0.0002 * W * H)):
            reasons.append("too small")
        if bx <= 1 or bX >= W - 2:
            reasons.append("touches frame edge (land, not a subject)")
        if h < 0.02 * H:
            reasons.append("too flat")
        if w > 0.12 * W:
            reasons.append("too wide (headland/shoreline, not a subject)")
        if tol < 1.0:
            # tol is how far the seed's colour sits from the nearest 5% of the
            # surrounding water, in characteristic colour units. Below one unit the
            # "subject" is the same colour as the sea -- it is a smooth patch of
            # swash that failed the texture test, not an object.
            reasons.append(f"colour indistinguishable from water (tol={tol:.2f})")
        picks.append(dict(run=(x0, x1), notch=round(float(notch[r].max()), 1),
                          tol=round(tol, 2), bbox=(by, bY, bx, bX),
                          area=int(blob.sum()), kept=not reasons,
                          rejected_for=reasons))
        if not reasons:
            fg |= blob
    return fg, picks


# ── beach ──────────────────────────────────────────────────────────────────
def _derive_beach(sea_bool, waterline, f, sky, W, H):
    """Sand: below the waterline, bright, smooth, non-blue, reaching the bottom edge.

    Cliffs and vines also touch the bottom edge but are dark and heavily textured,
    so an Otsu luminance split plus a texture percentile cap separates them
    without naming a coordinate. The bottom-edge anchor is what turns a colour
    classification into a single coherent shore.
    """
    lum, tex, blue_rel = f["lum"], f["tex"], f["blue_rel"]
    yy = np.arange(H, dtype=np.float64)[:, None]
    below = yy > (waterline[None, :] - 0.01 * H)
    zone = below & (sky < 0.5) & (~sea_bool)
    if zone.sum() < 64:
        return np.zeros((H, W), dtype=bool), dict(t_lum=None, t_tex=None)
    t_lum = _otsu(lum[zone], 0.0, 1.0)
    t_tex = float(np.percentile(tex[zone], 70))
    sand = zone & (lum > t_lum) & (tex < t_tex * 1.35) & (blue_rel < 0.35)
    sand = binary_opening(sand, structure=np.ones((5, 5), bool))
    sand = binary_closing(sand, structure=np.ones((15, 15), bool))
    seed = np.zeros((H, W), dtype=bool)
    seed[H - max(2, int(0.006 * H)):, :] = True
    anchored = _touching_components(sand, seed)
    if anchored.sum() > 0.15 * max(sand.sum(), 1):
        sand = anchored
    sand = binary_fill_holes(sand)
    return sand, dict(t_lum=float(t_lum), t_tex=t_tex)


# ── main entry point ───────────────────────────────────────────────────────
def derive_regions(
    image_path: str,
    size: Sequence[int] = (1920, 1080),
    seg_paths: Optional[Sequence[Optional[str]]] = None,
    method: str = "chroma_texture",
    feather_frac: float = 1.0 / 260.0,
    return_debug: bool = False,
):
    """Derive all named region masks from `image_path`.

    Parameters
    ----------
    seg_paths : (sky_png, water_png) from MotionCompositor._ensure_seg_masks.
                Omitted → looked up / computed via default_seg_provider.
    method    : sea/sand split. "chroma_texture" (default, and the one measured
                best), "chroma", or "luminance". See MEASURED_METHODS below.
    """
    W, H = int(size[0]), int(size[1])
    rgb = np.asarray(Image.open(image_path).convert("RGB").resize((W, H), Image.LANCZOS),
                     dtype=np.float32) / 255.0
    f = _features(rgb)

    if seg_paths is None:
        seg_paths = default_seg_provider(image_path)
    sky_p, water_p = (seg_paths + (None, None))[:2] if isinstance(seg_paths, tuple) \
        else (list(seg_paths) + [None, None])[:2]
    sky_soft = _load_mask(sky_p, W, H)
    water_soft = _load_mask(water_p, W, H)
    sky_soft = np.zeros((H, W), np.float32) if sky_soft is None else sky_soft
    water_soft = np.zeros((H, W), np.float32) if water_soft is None else water_soft

    feather = max(1.5, feather_frac * max(W, H))

    fire_b, _warm_px, fire_info = _derive_fire(f, W, H)
    firelight = _derive_firelight(fire_b, f, W, H)

    band = water_soft > 0.5
    debug = dict(fire=fire_info, band_cov=float(band.mean()))

    if band.sum() < 0.005 * W * H:
        sea_b = band.copy()
        waterline = np.full(W, H * 0.75, dtype=np.float64)
        beach_b = np.zeros((H, W), dtype=bool)
        fg_b = np.zeros((H, W), dtype=bool)
        debug["split"] = dict(feature="none", threshold=None)
    else:
        split = SEA_SPLIT_METHODS.get(method, sea_split_chroma_texture)
        sea_raw, split_info = split(f, band, W, H)
        debug["split"] = split_info
        sea_b = _solidify(sea_raw, band, W, H)
        waterline = _waterline(sea_b, W, H)
        fg_b, fg_picks = _derive_foreground(sea_b, waterline, f, W, H)
        debug["foreground_components"] = fg_picks
        beach_b, beach_info = _derive_beach(sea_b, waterline, f, sky_soft, W, H)
        debug["beach"] = beach_info
        beach_b &= ~fire_b

    debug["waterline"] = waterline
    debug["sea_solid_cov"] = float(sea_b.mean())

    # open water = sea, minus everything that is not sea
    yy = np.arange(H, dtype=np.float64)[:, None]
    open_b = (sea_b & (~beach_b) & (~fg_b) & (~fire_b)
              & (yy <= waterline[None, :] + max(2.0, 0.004 * H)))
    open_b = binary_opening(open_b, structure=np.ones((5, 5), bool))
    if open_b.any():
        open_b = _largest_components(open_b, min_area=int(0.0005 * W * H), keep_ratio=0.08)
        open_b = binary_fill_holes(open_b) & (~fg_b) & (~beach_b)

    sky_b = sky_soft > 0.5

    out = {
        "sky": _feather(sky_b, feather),
        "open_water": _feather(open_b, feather),
        "beach": _feather(beach_b & (~fg_b), feather),
        "fire": _feather(fire_b, max(1.5, feather * 0.6)),
        "firelight": gaussian_filter(firelight, sigma=feather, mode="nearest").astype(np.float32),
        "foreground": _feather(fg_b, max(1.5, feather * 0.7)),
    }
    # a subject must win over the water it stands in, and the sea must not bleed
    # back over sand: hard-subtract the exclusive regions from open_water
    excl = np.clip(out["foreground"] + out["beach"], 0.0, 1.0)
    out["open_water"] = np.clip(out["open_water"] * (1.0 - excl), 0.0, 1.0).astype(np.float32)
    out["sky"] = np.clip(out["sky"] * (1.0 - out["open_water"]), 0.0, 1.0).astype(np.float32)

    moving = np.clip(np.maximum(np.maximum(out["sky"], out["open_water"]), out["fire"]),
                     0.0, 1.0)
    out["static"] = np.clip(1.0 - moving, 0.0, 1.0).astype(np.float32)

    for k in out:
        out[k] = np.ascontiguousarray(out[k], dtype=np.float32)

    if return_debug:
        return out, debug
    return out


# ── reporting helpers ──────────────────────────────────────────────────────
def coverage(masks: dict) -> dict:
    """Fraction of the frame each mask covers, weighted by mask value."""
    return {k: float(v.mean()) for k, v in masks.items()}


def overlap_matrix(masks: dict, names: Sequence[str] = REGION_NAMES) -> np.ndarray:
    """M[i, j] = fraction of mask i's energy that also lies in mask j."""
    names = [n for n in names if n in masks]
    m = np.zeros((len(names), len(names)), dtype=np.float64)
    for i, a in enumerate(names):
        sa = float(masks[a].sum())
        for j, b in enumerate(names):
            m[i, j] = float(np.minimum(masks[a], masks[b]).sum()) / max(sa, 1e-9)
    return m


def bbox_of(mask: np.ndarray, thresh: float = 0.5):
    ys, xs = np.nonzero(mask > thresh)
    if ys.size == 0:
        return None
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


_OVERLAY_COLORS = {
    "sky":        (60, 90, 220),
    "open_water": (0, 190, 255),
    "beach":      (255, 210, 90),
    "fire":       (255, 60, 0),
    "firelight":  (255, 150, 40),
    "foreground": (255, 0, 200),
    "static":     (120, 120, 120),
}


def overlay_png(image_path: str, masks: dict, out_path: str,
                size: Sequence[int] = (1920, 1080),
                show: Sequence[str] = ("sky", "open_water", "beach", "firelight",
                                       "fire", "foreground"),
                waterline: Optional[np.ndarray] = None,
                alpha: float = 0.45) -> str:
    W, H = int(size[0]), int(size[1])
    base = np.asarray(Image.open(image_path).convert("RGB").resize((W, H), Image.LANCZOS),
                      dtype=np.float32)
    out = base * 0.55
    for name in show:
        if name not in masks:
            continue
        col = np.array(_OVERLAY_COLORS.get(name, (255, 255, 255)), dtype=np.float32)
        m = masks[name][:, :, None]
        out = out * (1.0 - alpha * m) + col[None, None, :] * (alpha * m)
    if waterline is not None:
        for x in range(W):
            y = int(round(float(waterline[x])))
            for dy in (-1, 0, 1):
                yy = y + dy
                if 0 <= yy < H:
                    out[yy, x] = (255.0, 255.0, 255.0)
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(out_path)
    return out_path
