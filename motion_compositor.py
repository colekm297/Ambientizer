"""
motion_compositor.py — Procedural, seamlessly-looping motion over a still image.

The problem this solves: AI video (Grok/Runway/MJ) produces clips that are too
dynamic and do NOT loop, so they can't fill an hour-long ambient video without a
visible seam every few seconds. Ken Burns zoom only moves one direction, so it
also jumps when looped.

This module composites PERIODIC motion layers over a still. Every layer returns
to its exact starting state at the loop point (t=0 and t=T are identical), so a
short loop (default 16s) tiles across an hour with zero visible seam — and it
costs $0 (pure numpy/Pillow + ffmpeg, no API calls).

Motion layers (all loop-seamless by construction):
  - breathing_zoom : cosine zoom + optional orbital drift (camera returns to start)
  - particles      : snow / rain / embers / dust / fireflies / bokeh (phase-wrapped)
  - fog            : drifting soft noise, screen-blended (tiling → wraps seamlessly)
  - light          : gentle global brightness/saturation breathing
  - vignette_pulse : slow edge-darkening pulse

Usage:
    mc = MotionCompositor()
    mc.render(
        image_path="scene.png",
        output_path="scene_loop.mp4",
        layers=[
            {"type": "breathing_zoom", "amount": 0.10, "orbit": 0.4},
            {"type": "particles", "kind": "dust", "count": 220, "amount": 0.6},
            {"type": "fog", "amount": 0.25},
            {"type": "light", "amount": 0.12},
            {"type": "vignette_pulse", "amount": 0.18},
        ],
        loop_sec=16, fps=24, size=(1920, 1080),
    )

The output is a seamless loop; feed it to VisualGenerator.loop_video() to fill
the full track duration.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates


TWO_PI = 2.0 * math.pi


# ── Particle presets ───────────────────────────────────────────────────────
# Each preset describes how a particle field looks and moves. Velocities are in
# "screen-fractions per loop" and are forced to integer cycle counts so the field
# returns to its start at the loop point.
PARTICLE_PRESETS = {
    "snow":      dict(vy=1, vx=0,  drift=0.06, size=(2.0, 4.5), bright=0.9,  blur=1.1, streak=0.0, twinkle=0.15),
    "rain":      dict(vy=3, vx=0,  drift=0.02, size=(1.0, 1.8), bright=0.55, blur=0.6, streak=9.0, twinkle=0.0),
    "embers":    dict(vy=-1, vx=0, drift=0.10, size=(1.5, 3.5), bright=1.0,  blur=1.4, streak=0.0, twinkle=0.5,  warm=True),
    "dust":      dict(vy=0, vx=1,  drift=0.05, size=(1.5, 3.0), bright=0.6,  blur=1.3, streak=0.0, twinkle=0.25),
    "fireflies": dict(vy=0, vx=0,  drift=0.12, size=(2.0, 4.0), bright=1.0,  blur=1.6, streak=0.0, twinkle=0.85, warm=True),
    "bokeh":     dict(vy=0, vx=1,  drift=0.04, size=(6.0, 16.0),bright=0.5,  blur=3.0, streak=0.0, twinkle=0.4),
}


class MotionCompositor:
    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg = ffmpeg_bin

    # ── public API ──────────────────────────────────────────────────────────
    def render(
        self,
        image_path: str,
        output_path: Optional[str] = None,
        layers: Optional[list[dict]] = None,
        loop_sec: float = 16.0,
        fps: int = 24,
        size: tuple[int, int] = (1920, 1080),
        crf: int = 18,
        on_status=None,
        brush_mask_path: Optional[str] = None,
    ) -> str:
        """Render a seamless motion loop. Returns the output path.

        brush_mask_path: optional PNG where WHITE = "this region moves" and BLACK =
        "freeze". When given, motion is confined to the painted region and everything
        else stays pixel-perfect static (the global camera is anchored), like a
        motion brush. The mask is feathered so the boundary isn't a hard cut."""
        layers = layers if layers is not None else self.default_layers()
        if not output_path:
            output_path = str(Path(image_path).with_suffix("")) + "_motionloop.mp4"

        W, H = size
        n_frames = max(1, int(round(loop_sec * fps)))

        def status(msg):
            print(f"  [motion] {msg}", flush=True)
            if on_status:
                on_status(msg)

        status(f"Rendering {loop_sec:.0f}s seamless loop @ {fps}fps ({W}x{H}, {len(layers)} layer(s))")

        # ── Motion-brush mask ────────────────────────────────────────────────
        # WHITE = moves, BLACK = frozen. We anchor the global camera (so frozen
        # pixels never drift) and, at the end of each frame, blend the animated
        # frame back over the static original everywhere the mask is black.
        brush_mask = None
        if brush_mask_path:
            brush_mask = self._load_brush_mask(brush_mask_path, W, H)
            if brush_mask is not None:
                status("motion brush mask loaded — freezing unpainted regions")
            else:
                status("brush mask empty/unreadable — ignoring")

        # Pre-build per-layer state that's constant across frames.
        zoom_cfg = _find(layers, "breathing_zoom")
        zmax = 1.0 + (zoom_cfg.get("amount", 0.10) if zoom_cfg else 0.0)
        orbit = (zoom_cfg.get("orbit", 0.0) if zoom_cfg else 0.0)
        pan = (zoom_cfg.get("pan", 0.0) if zoom_cfg else 0.0)
        # In brush mode the camera is ANCHORED — a global zoom/pan would make the
        # frozen region mismatch the static base at the mask edge. Motion comes
        # entirely from the in-region effects (nebula drift, twinkle, particles…).
        if brush_mask is not None:
            zmax, orbit, pan = 1.0, 0.0, 0.0
        # A pan needs crop headroom to glide within — guarantee some zoom-in.
        if pan > 0.01:
            zmax = max(zmax, 1.18)

        base_big = self._load_base(image_path, W, H, zmax)
        base_pil = Image.fromarray(base_big.astype(np.uint8))  # for sub-pixel camera sampling

        # Frozen reference for brush mode: the anchored camera output (identical at
        # every t), so unpainted regions blend back to exactly this every frame.
        static_base = None
        brush_m3 = None
        if brush_mask is not None:
            static_base = self._camera_frame(base_pil, W, H, zmax, orbit, 0.0, pan)
            brush_m3 = brush_mask[:, :, None]
        particle_fields = [self._make_particle_field(l, W, H) for l in layers if l["type"] == "particles"]
        fog_cfg = _find(layers, "fog")
        fog_tex = self._make_fog_texture(W, H) if fog_cfg else None
        light_cfg = _find(layers, "light")
        vign_cfg = _find(layers, "vignette_pulse")
        vignette = self._make_vignette(W, H) if vign_cfg else None
        # premium layers
        rays_cfg = _find(layers, "god_rays")
        rays_state = self._make_god_rays(W, H, rays_cfg) if rays_cfg else None
        shimmer_cfg = _find(layers, "shimmer")
        shimmer_state = self._make_shimmer(W, H, shimmer_cfg) if shimmer_cfg else None
        aurora_cfg = _find(layers, "aurora")
        aurora_state = self._make_aurora(W, H, aurora_cfg) if aurora_cfg else None
        parallax_cfg = _find(layers, "parallax")
        parallax_state = self._make_parallax(image_path, W, H, parallax_cfg) if parallax_cfg else None
        if parallax_state is not None:
            status("depth map ready — using 2.5D parallax camera")
        glow_cfg = _find(layers, "color_glow")
        glow_mask = self._make_glow(W, H) if glow_cfg else None
        twinkle_cfg = _find(layers, "twinkle")
        twinkle_state = self._make_twinkle(W, H, twinkle_cfg) if twinkle_cfg else None

        # Nebula: auto-masked by CONTENT (colored, mid-bright gas), not semantic
        # segmentation — ADE20K "sky" doesn't fire on stylized space art.
        nebula_cfg = _find(layers, "nebula")
        nebula_mask = self._nebula_mask(W, H, base_pil) if nebula_cfg else None

        # Water shimmer DOES use segmentation (real water scenes are in-distribution).
        water_mask = None
        need_water = shimmer_cfg is not None and shimmer_cfg.get("region") == "water"
        if need_water:
            status("segmenting scene (water)...")
            _, water_p = self._ensure_seg_masks(image_path)
            water_mask = self._load_region_mask(water_p, W, H)
            status("water mask ready" if water_mask is not None
                   else "no water found — shimmer skipped")

        proc = self._open_ffmpeg(output_path, W, H, fps, crf)
        try:
            for i in range(n_frames):
                t = i / n_frames  # normalized [0,1); t=0 == t=1 → seamless
                if parallax_state is not None:
                    frame = self._parallax_frame(parallax_state, t)
                else:
                    frame = self._camera_frame(base_pil, W, H, zmax, orbit, t, pan)

                if shimmer_state is not None:
                    sh = self._apply_shimmer(frame, shimmer_state, t)
                    region = shimmer_cfg.get("region")
                    if region == "water":
                        if water_mask is not None:        # confine to water; skip if none found
                            m = water_mask[:, :, None]
                            frame = frame * (1.0 - m) + sh * m
                    else:
                        frame = sh                        # whole-frame shimmer (no region)

                if nebula_mask is not None:
                    self._apply_region_warp(frame, nebula_mask, t, nebula_cfg.get("amount", 0.5))

                for field in particle_fields:
                    self._draw_particles(frame, field, t)

                if twinkle_state is not None:
                    self._apply_twinkle(frame, twinkle_state, t)

                if rays_state is not None:
                    self._apply_god_rays(frame, rays_state, t)
                if aurora_state is not None:
                    self._apply_aurora(frame, aurora_state, t)

                if fog_tex is not None:
                    self._apply_fog(frame, fog_tex, fog_cfg.get("amount", 0.25), t)

                if light_cfg is not None:
                    self._apply_light(frame, light_cfg.get("amount", 0.12), t)

                if vignette is not None:
                    self._apply_vignette(frame, vignette, vign_cfg.get("amount", 0.18), t)

                if glow_mask is not None:
                    self._apply_color_glow(frame, glow_mask, glow_cfg, t)

                # Motion brush: keep motion only where painted; restore the frozen
                # original everywhere else (feathered edge avoids a hard seam).
                if static_base is not None:
                    frame = static_base * (1.0 - brush_m3) + frame * brush_m3

                np.clip(frame, 0, 255, out=frame)
                proc.stdin.write(frame.astype(np.uint8).tobytes())

                if on_status and i % max(1, n_frames // 40) == 0:
                    status(f"frame {i + 1}/{n_frames}")
        finally:
            proc.stdin.close()
            ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"ffmpeg encode failed (exit {ret})")

        status(f"Done → {output_path}")
        return output_path

    @staticmethod
    def default_layers() -> list[dict]:
        return [
            {"type": "breathing_zoom", "amount": 0.10, "orbit": 0.4},
            {"type": "particles", "kind": "dust", "count": 200, "amount": 0.55},
            {"type": "fog", "amount": 0.22},
            {"type": "light", "amount": 0.10},
            {"type": "vignette_pulse", "amount": 0.16},
        ]

    # ── camera ────────────────────────────────────────────────────────────
    def _load_base(self, image_path: str, W: int, H: int, zmax: float) -> np.ndarray:
        """Upscaled base so the zoom always crops real pixels (stays sharp)."""
        big_w, big_h = int(round(W * zmax)) + 2, int(round(H * zmax)) + 2
        im = Image.open(image_path).convert("RGB")
        # Cover-fit to the big canvas (preserve aspect, crop overflow).
        im = _cover_resize(im, big_w, big_h)
        return np.asarray(im, dtype=np.float32)

    def _camera_frame(self, base_pil, W, H, zmax, orbit, t, pan=0.0) -> np.ndarray:
        # SUB-PIXEL camera. The old version cropped at integer pixel offsets
        # (int(round(...))) every frame, so smooth motion quantized into 1-2px
        # jumps → a visible shake/jitter. We now sample with a float affine
        # transform (bilinear), so the drift is perfectly smooth.
        bw, bh = base_pil.size
        # Cosine breathing: z(0)=1, peaks at mid, z(1)=1 → seamless.
        z = 1.0 + (zmax - 1.0) * (1.0 - math.cos(TWO_PI * t)) * 0.5
        win_w = min(W * (zmax / z), float(bw))
        win_h = min(H * (zmax / z), float(bh))

        # Crop-centre drift over the loop (returns to start → seamless).
        #  orbit = gentle circular drift; pan = stronger, mostly-HORIZONTAL glide
        #  across the scene (suppresses vertical so it reads as a camera pan, not a wobble).
        slack_x = bw - win_w
        slack_y = bh - win_h
        amp_x = max(orbit, pan)
        amp_y = orbit * (1.0 - 0.9 * pan)
        fx = slack_x * 0.5 + math.cos(TWO_PI * t) * slack_x * 0.5 * amp_x
        fy = slack_y * 0.5 + math.sin(TWO_PI * t) * slack_y * 0.5 * amp_y
        fx = min(max(fx, 0.0), slack_x)
        fy = min(max(fy, 0.0), slack_y)

        # Output pixel (X,Y) samples base at (fx + X*win_w/W, fy + Y*win_h/H).
        a = win_w / W
        e = win_h / H
        out = base_pil.transform((W, H), Image.AFFINE, (a, 0.0, fx, 0.0, e, fy),
                                 resample=Image.BILINEAR)
        return np.asarray(out, dtype=np.float32)

    # ── particles ───────────────────────────────────────────────────────────
    def _make_particle_field(self, layer: dict, W: int, H: int) -> dict:
        kind = layer.get("kind", "dust")
        preset = dict(PARTICLE_PRESETS.get(kind, PARTICLE_PRESETS["dust"]))
        n = int(layer.get("count", 200))
        rng = np.random.default_rng(layer.get("seed", 1234))

        px = rng.random(n).astype(np.float32)          # start positions, normalized
        py = rng.random(n).astype(np.float32)
        # INTEGER traversals-per-loop is what makes the field seamless: at t=1 the
        # position is (px + integer) % 1 == px, i.e. exactly back where it started.
        cyc_x = int(preset["vx"])
        cyc_y = int(preset["vy"])
        # Fields with no net velocity (fireflies) get a tiny circular wander instead.
        wander = (cyc_x == 0 and cyc_y == 0)
        sizes = rng.uniform(preset["size"][0], preset["size"][1], n).astype(np.float32)
        phase = rng.random(n).astype(np.float32)
        tw_cyc = rng.integers(1, 4, n).astype(np.float32)  # twinkle cycles per loop (integer)
        return dict(
            preset=preset, W=W, H=H, n=n, px=px, py=py,
            cyc_x=cyc_x, cyc_y=cyc_y,
            wander=wander, sizes=sizes, phase=phase, tw_cyc=tw_cyc,
            amount=float(layer.get("amount", 0.6)),
        )

    def _draw_particles(self, frame: np.ndarray, field: dict, t: float):
        W, H, p = field["W"], field["H"], field["preset"]
        # Positions wrap modulo 1 → seamless. Margin so they enter/exit off-frame.
        if field["wander"]:
            wob = p["drift"]
            x = (field["px"] + np.cos(TWO_PI * (t + field["phase"])) * wob) % 1.0
            y = (field["py"] + np.sin(TWO_PI * (t + field["phase"])) * wob) % 1.0
        else:
            # cyc_* are integer traversals per loop → x(t=1) == x(t=0): seamless.
            x = (field["px"] + field["cyc_x"] * t) % 1.0
            y = (field["py"] + field["cyc_y"] * t) % 1.0

        twinkle = 1.0 - p["twinkle"] * (0.5 - 0.5 * np.cos(TWO_PI * (field["tw_cyc"] * t + field["phase"])))
        bright = p["bright"] * field["amount"] * twinkle

        # Splat onto a half-res accumulation buffer, blur once, then add.
        hw, hh = W // 2, H // 2
        acc = np.zeros((hh, hw), dtype=np.float32)
        xi = np.clip((x * hw).astype(np.int32), 0, hw - 1)
        yi = np.clip((y * hh).astype(np.int32), 0, hh - 1)
        np.add.at(acc, (yi, xi), bright)

        # Rain draws short vertical streaks.
        if p["streak"] > 0:
            for s in range(1, int(p["streak"])):
                yy = np.clip(yi - s, 0, hh - 1)
                np.add.at(acc, (yy, xi), bright * (1 - s / p["streak"]))

        acc = gaussian_filter(acc, sigma=max(0.4, p["blur"]))
        glow = np.asarray(
            Image.fromarray(np.clip(acc * 255, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR),
            dtype=np.float32,
        )[:, :, None]

        if p.get("warm"):
            tint = np.array([1.0, 0.72, 0.38], dtype=np.float32)
        else:
            tint = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        # Screen blend: brighten without blowing out.
        frame += (255.0 - frame) * (glow / 255.0) * tint

    # ── fog ───────────────────────────────────────────────────────────────
    def _make_fog_texture(self, W: int, H: int) -> np.ndarray:
        """Soft-noise texture with horizontal period == W, tiled to width 2W.

        Because the period is exactly W and we scroll exactly W per loop, the
        wrap (t=1 → t=0) lands on an identical column → seamless.
        """
        rng = np.random.default_rng(7)
        base = rng.random((H // 8, W // 8)).astype(np.float32)
        base = np.asarray(
            Image.fromarray((base * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC),
            dtype=np.float32,
        )
        base = gaussian_filter(base, sigma=18, mode="wrap")  # wrap mode keeps it tileable
        # Force exact horizontal tileability: blend the tile with its half-roll so
        # the left/right edges meet continuously.
        rolled = np.roll(base, W // 2, axis=1)
        ramp = np.abs(np.linspace(-1.0, 1.0, W, dtype=np.float32))[None, :]  # 1 at edges, 0 centre
        tile = base * (1.0 - ramp) + rolled * ramp
        tile -= tile.min()
        tile /= max(tile.max(), 1e-5)
        return np.concatenate([tile, tile], axis=1)  # width 2W, period W

    def _apply_fog(self, frame, fog_tex, amount, t):
        H, W2 = fog_tex.shape
        W = frame.shape[1]
        off = int((t * W) % W)  # one full tile traverse per loop → seamless
        strip = fog_tex[:, off:off + W]
        if strip.shape[1] < W:  # wrap
            strip = np.concatenate([strip, fog_tex[:, :W - strip.shape[1]]], axis=1)
        veil = (strip[:, :, None] * amount * 255.0)
        frame += (255.0 - frame) * (veil / 255.0)

    # ── light + vignette ──────────────────────────────────────────────────
    def _apply_light(self, frame, amount, t):
        # Brightness breathing, returns to 1.0 at the loop point.
        g = 1.0 + amount * math.sin(TWO_PI * t)
        frame *= g

    def _make_vignette(self, W, H) -> np.ndarray:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        cx, cy = W / 2, H / 2
        r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
        v = np.clip(r - 0.6, 0, None)
        v /= max(v.max(), 1e-5)
        return v[:, :, None]

    def _apply_vignette(self, frame, vignette, amount, t):
        depth = amount * (0.5 - 0.5 * math.cos(TWO_PI * t))  # 0→amount→0
        frame *= (1.0 - vignette * depth)

    # ── colored glow (edge-weighted light wash that slowly breathes) ────────
    def _make_glow(self, W, H) -> np.ndarray:
        """Edge-weighted mask (strong at the frame edges, fading to centre) so a
        colored glow reads like ambient lighting spilling in — e.g. a ship's red
        alert glow — rather than a flat color cast."""
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        cx, cy = W / 2, H / 2
        r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
        m = np.clip((r - 0.35) / 0.9, 0.0, 1.0)
        return (m * m)[:, :, None]   # ease-in toward the edges

    def _apply_color_glow(self, frame, glow_mask, cfg, t):
        color = np.array(_GLOW_COLORS.get(cfg.get("color", "red"), _GLOW_COLORS["red"]),
                         dtype=np.float32)
        amount = float(cfg.get("amount", 0.25))
        # Slow breathing pulse that never fully vanishes (steady ambient presence).
        pulse = amount * (0.62 + 0.38 * (0.5 - 0.5 * math.cos(TWO_PI * t)))
        frame += glow_mask * pulse * color[None, None, :]

    # ── twinkle (make the image's own bright spots flicker/breathe) ─────────
    def _make_twinkle(self, W, H, cfg) -> dict:
        """Per-pixel phase field so bright spots twinkle OUT of sync (a city of
        lights, a starfield), not all at once. Integer cycle count keeps it
        seamless across the loop."""
        # VERY low-frequency phase, heavily blurred → whole bright REGIONS pulse
        # together (a soft breathing), instead of fine per-pixel modulation that
        # made a busy "maze" flicker over detailed surfaces like a painted city.
        from scipy.ndimage import gaussian_filter
        rng = np.random.default_rng(7)
        low = rng.random((max(2, H // 30), max(2, W // 30))).astype(np.float32)
        phase = np.asarray(
            Image.fromarray((low * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR),
            dtype=np.float32,
        ) / 255.0
        phase = gaussian_filter(phase, sigma=max(W, H) / 60.0)
        return {
            "phase": phase,
            "amount": min(0.45, float(cfg.get("amount", 0.4)) * 0.6),  # gentle swing
            "thresh": float(cfg.get("threshold", 120.0)),
            "cycles": 3,  # integer → seamless loop
            "blur": max(1.0, max(W, H) / 200.0),
        }

    def _nebula_mask(self, W, H, base_pil) -> np.ndarray:
        """Auto-mask the colored gas/nebula by CONTENT: saturated, mid-bright
        pixels (not the black void, not the blown-out bright core). Robust on
        stylized space art where semantic 'sky' segmentation fails."""
        from scipy.ndimage import gaussian_filter
        arr = np.asarray(base_pil.resize((W, H), Image.BILINEAR), dtype=np.float32)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        mx = np.maximum(np.maximum(r, g), b)
        mn = np.minimum(np.minimum(r, g), b)
        lum = (r + g + b) / 3.0
        sat = (mx - mn) / (mx + 1e-3)
        m = ((sat > 0.10) & (lum > 22) & (lum < 205)).astype(np.float32)
        m = gaussian_filter(m, sigma=max(W, H) / 150.0)
        mx2 = float(m.max())
        return np.clip(m / mx2, 0.0, 1.0) if mx2 > 1e-6 else m

    def _apply_twinkle(self, frame, st, t):
        # Bright-region mask straight off the CURRENT frame, so it tracks the
        # camera move and any overlaid stars. Dark areas (space) stay untouched.
        from scipy.ndimage import gaussian_filter
        lum = frame.mean(axis=2)
        denom = max(1.0, 255.0 - st["thresh"])
        mask = np.clip((lum - st["thresh"]) / denom, 0.0, 1.0)
        # Soften the mask so bright REGIONS breathe smoothly (no per-pixel sparkle/maze).
        mask = gaussian_filter(mask, sigma=st.get("blur", 4.0))
        osc = np.sin(TWO_PI * (st["cycles"] * t + st["phase"]))  # [-1,1], seamless
        factor = 1.0 + st["amount"] * mask * osc
        frame *= factor[:, :, None]

    # ── premium: 2.5D depth parallax ─────────────────────────────────────
    def _ensure_depth_map(self, image_path: str) -> Optional[str]:
        """Return a cached depth map path, estimating one (via system python3.13
        + Depth-Anything) if absent. Returns None if estimation fails."""
        import subprocess
        src = Path(image_path)
        depth_path = src.with_name(src.stem + "_depth.png")
        if depth_path.exists():
            return str(depth_path)
        script = str(Path(__file__).with_name("depth_estimator.py"))
        # Absolute path: the app runs under launchd with a minimal PATH where a
        # bare "python3.13" wouldn't resolve. Fall back to PATH lookup if moved.
        py = "/opt/homebrew/bin/python3.13"
        if not Path(py).exists():
            py = "python3.13"
        try:
            subprocess.run([py, script, str(image_path), str(depth_path)],
                           check=True, capture_output=True, timeout=300)
        except Exception as e:
            print(f"  [motion] depth estimation failed ({e}); parallax disabled", flush=True)
            return None
        return str(depth_path) if depth_path.exists() else None

    def _ensure_seg_masks(self, image_path: str):
        """Return (sky_mask_path, water_mask_path), running semantic segmentation
        (system python3.13 + Segformer/ADE20K) once per image and caching. Returns
        (None, None) on failure so region effects just no-op."""
        import subprocess
        src = Path(image_path)
        sky_p = src.with_name(src.stem + "_seg_sky.png")
        water_p = src.with_name(src.stem + "_seg_water.png")
        if sky_p.exists() and water_p.exists():
            return str(sky_p), str(water_p)
        script = str(Path(__file__).with_name("segmenter.py"))
        py = "/opt/homebrew/bin/python3.13"
        if not Path(py).exists():
            py = "python3.13"
        try:
            subprocess.run([py, script, str(image_path), str(sky_p), str(water_p)],
                           check=True, capture_output=True, timeout=600)
        except Exception as e:
            print(f"  [motion] segmentation failed ({e}); region effects disabled", flush=True)
            return None, None
        ok = sky_p.exists() and water_p.exists()
        return (str(sky_p), str(water_p)) if ok else (None, None)

    @staticmethod
    def _load_region_mask(path, W, H):
        """Load a cached mask PNG → float32 [0,1] array at (H,W), or None."""
        if not path or not Path(path).exists():
            return None
        m = np.asarray(Image.open(path).convert("L").resize((W, H), Image.BILINEAR),
                       dtype=np.float32) / 255.0
        return m if m.max() > 0.02 else None  # treat an empty mask as "not present"

    @staticmethod
    def _load_brush_mask(path, W, H):
        """Load a hand-painted motion mask (WHITE=move) → feathered float32 [0,1] at
        (H,W). Uses the alpha channel if present (transparent canvas + white strokes),
        else luminance. Returns None if effectively empty."""
        if not path or not Path(path).exists():
            return None
        try:
            im = Image.open(path)
            if "A" in im.getbands():
                m = np.asarray(im.convert("RGBA").split()[-1], dtype=np.float32)
            else:
                m = np.asarray(im.convert("L"), dtype=np.float32)
        except Exception:
            return None
        # Resize to render size, normalize, then feather the edges so the boundary
        # between moving and frozen isn't a hard cut.
        m = np.asarray(Image.fromarray(m.astype(np.uint8)).resize((W, H), Image.BILINEAR),
                       dtype=np.float32) / 255.0
        if m.max() <= 0.02:
            return None
        m = gaussian_filter(m, sigma=max(4.0, W / 240.0))
        return np.clip(m, 0.0, 1.0)

    def _apply_region_warp(self, frame, mask, t, amount):
        """Slow flowing displacement confined to a region (nebula/gas drifting in
        the sky). Sinusoidal field with integer cycles → seamless loop."""
        from scipy.ndimage import map_coordinates
        H, W, _ = frame.shape
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        amp = amount * 16.0
        ph = TWO_PI * t
        scale = max(80.0, W / 9.0)
        dx = amp * np.sin(2 * np.pi * yy / scale + ph)
        dy = amp * 0.55 * np.cos(2 * np.pi * xx / scale + ph)
        sx = np.clip(xx + dx, 0, W - 1)
        sy = np.clip(yy + dy, 0, H - 1)
        m = mask[:, :, None]
        for c in range(3):
            warped = map_coordinates(frame[:, :, c], [sy, sx], order=1, mode="reflect")
            frame[:, :, c] = frame[:, :, c] * (1.0 - m[:, :, 0]) + warped * m[:, :, 0]

    def _make_parallax(self, image_path, W, H, cfg) -> Optional[dict]:
        cfg = cfg or {}
        depth_path = self._ensure_depth_map(image_path)
        if not depth_path:
            return None
        base = np.asarray(_cover_resize(Image.open(image_path).convert("RGB"), W, H), dtype=np.float32)
        depth = np.asarray(_cover_resize(Image.open(depth_path).convert("L"), W, H), dtype=np.float32) / 255.0
        depth = gaussian_filter(depth, sigma=2.0)  # soften so warp edges aren't jagged
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        return dict(base=base, depth=depth, yy=yy, xx=xx,
                    amp=float(cfg.get("amount", 0.5)) * 0.045 * W,  # max ~4.5% shift
                    W=W, H=H)

    def _parallax_frame(self, st, t) -> np.ndarray:
        # Elliptical camera orbit, returns to start at t=1 → seamless. Near pixels
        # (high depth) shift more than far ones → real parallax. Backward-warp
        # sampling means no disocclusion holes.
        cam_x = math.sin(TWO_PI * t) * st["amp"]
        cam_y = math.cos(TWO_PI * t) * st["amp"] * 0.5
        sample_x = st["xx"] + st["depth"] * cam_x
        sample_y = st["yy"] + st["depth"] * cam_y
        coords = np.array([sample_y.ravel(), sample_x.ravel()])
        out = np.empty_like(st["base"])
        for c in range(3):
            out[:, :, c] = map_coordinates(
                st["base"][:, :, c], coords, order=1, mode="reflect"
            ).reshape(st["H"], st["W"])
        return out

    # ── premium: god-rays (crepuscular light beams) ──────────────────────
    def _make_god_rays(self, W, H, cfg) -> dict:
        cfg = cfg or {}
        sx = cfg.get("source_x", 0.78) * W   # light source, default upper-right
        sy = cfg.get("source_y", -0.10) * H
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        ang = np.arctan2(yy - sy, xx - sx)
        dist = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2)
        falloff = np.clip(1.0 - dist / (math.hypot(W, H) * 1.1), 0.0, 1.0) ** 1.5
        warm = cfg.get("warm", True)
        tint = np.array([1.0, 0.85, 0.6] if warm else [0.8, 0.9, 1.0], dtype=np.float32)
        return dict(ang=ang, falloff=falloff, n=int(cfg.get("count", 7)),
                    amount=float(cfg.get("amount", 0.5)), tint=tint)

    def _apply_god_rays(self, frame, st, t):
        drift = TWO_PI * t                       # one full cycle per loop → seamless
        rays = 0.5 + 0.5 * np.sin(st["ang"] * st["n"] + drift)
        rays = rays ** 2                         # sharpen into distinct beams
        pulse = 0.75 + 0.25 * math.cos(TWO_PI * t)
        glow = (rays * st["falloff"] * st["amount"] * pulse)[:, :, None] * st["tint"]
        frame += (255.0 - frame) * glow          # screen blend

    # ── premium: shimmer (water / heat / sky wavering) ───────────────────
    def _make_shimmer(self, W, H, cfg) -> dict:
        cfg = cfg or {}
        return dict(
            amp=float(cfg.get("amount", 0.5)) * 9.0,        # px of horizontal sway
            base_cols=np.arange(W, dtype=np.float32)[None, :],
            yy=np.arange(H, dtype=np.float32)[:, None],
            W=W, wav=float(cfg.get("wavelength", 110.0)),
        )

    def _apply_shimmer(self, frame, st, t):
        cyc = 2                                  # integer cycles per loop → seamless
        offs = st["amp"] * np.sin(TWO_PI * (st["yy"] / st["wav"] + cyc * t))  # (H,1)
        idx = ((st["base_cols"] + offs) % st["W"]).astype(np.int32)          # (H,W)
        np.clip(idx, 0, st["W"] - 1, out=idx)  # float % can round up to W at the edge
        return np.take_along_axis(frame, idx[:, :, None].repeat(3, axis=2), axis=1)

    # ── premium: aurora (flowing colored curtains) ───────────────────────
    def _make_aurora(self, W, H, cfg) -> dict:
        cfg = cfg or {}
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        ynorm = yy / H
        mask = np.clip(1.0 - ynorm * 1.8, 0.0, 1.0) ** 1.5   # strongest at top
        return dict(xnorm=xx / W, ynorm=ynorm, mask=mask,
                    amount=float(cfg.get("amount", 0.5)))

    def _apply_aurora(self, frame, st, t):
        x, y = st["xnorm"], st["ynorm"]
        band1 = 0.5 + 0.5 * np.sin(TWO_PI * (x * 2 + t) + y * 6)
        band2 = 0.5 + 0.5 * np.sin(TWO_PI * (x * 3 - t) + y * 9 + 1.7)
        curtain = (band1 * 0.6 + band2 * 0.4) ** 2 * st["mask"] * st["amount"]
        glow = (curtain[:, :, None] * np.array([0.25, 1.0, 0.55], dtype=np.float32)
                + (curtain * 0.5)[:, :, None] * np.array([0.6, 0.3, 1.0], dtype=np.float32))
        frame += (255.0 - frame) * glow          # screen blend

    # ── ffmpeg ──────────────────────────────────────────────────────────────
    def _open_ffmpeg(self, output_path, W, H, fps, crf):
        cmd = [
            self.ffmpeg, "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{W}x{H}", "-r", str(fps),
            "-i", "-",
            "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            # tune for the inevitable loop tiling: keyframe every loop helps seeking
            "-g", str(fps * 2),
            output_path,
        ]
        return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)


# ── Scene presets ──────────────────────────────────────────────────────────
# Tuned intensities: clearly visible but tasteful (between "too subtle" and the
# over-cranked demo). Claude (or keyword matching) picks one per scene; the
# values can still be overridden per layer.
SCENE_PRESETS = {
    "space": [
        # Space images already have their own painted starfield — so we just
        # slowly drift the whole image (its stars move with it) instead of
        # overlaying more particles. NO fog: drifting mist reads as clouds in
        # a vacuum. The twinkle layer makes the existing bright spots (city
        # lights, stars, consoles) flicker/breathe — the scene comes alive
        # without touching the dark areas.
        {"type": "breathing_zoom", "amount": 0.10, "orbit": 0.5},
        {"type": "twinkle", "amount": 0.8},
        {"type": "nebula", "amount": 0.5, "region": "sky"},  # drift the gas/nebula, sky only
        {"type": "light", "amount": 0.07},
        {"type": "vignette_pulse", "amount": 0.14},
    ],
    "rain": [
        {"type": "breathing_zoom", "amount": 0.07, "orbit": 0.3},
        {"type": "particles", "kind": "rain", "count": 420, "amount": 0.7, "seed": 5},
        {"type": "fog", "amount": 0.30},
        {"type": "light", "amount": 0.07},
        {"type": "vignette_pulse", "amount": 0.14},
    ],
    "snow": [
        {"type": "breathing_zoom", "amount": 0.09, "orbit": 0.4},
        {"type": "particles", "kind": "snow", "count": 240, "amount": 0.9, "seed": 2},
        {"type": "fog", "amount": 0.20},
        {"type": "light", "amount": 0.09},
    ],
    "fireplace": [
        {"type": "breathing_zoom", "amount": 0.08, "orbit": 0.3},
        {"type": "particles", "kind": "embers", "count": 130, "amount": 1.0, "seed": 4},
        {"type": "fog", "amount": 0.15},
        {"type": "light", "amount": 0.18},  # firelight flicker
    ],
    "forest": [
        {"type": "breathing_zoom", "amount": 0.10, "orbit": 0.5},
        {"type": "god_rays", "amount": 0.5, "count": 8, "warm": True},  # sunbeams through canopy
        {"type": "particles", "kind": "dust", "count": 160, "amount": 0.6, "seed": 6},  # sunbeam motes
        {"type": "particles", "kind": "fireflies", "count": 50, "amount": 0.7, "seed": 8},
        {"type": "fog", "amount": 0.28},
        {"type": "light", "amount": 0.10},
    ],
    "ocean": [
        {"type": "breathing_zoom", "amount": 0.09, "orbit": 0.6},
        {"type": "shimmer", "amount": 0.5, "region": "water"},  # ripple ONLY on the water
        {"type": "particles", "kind": "bokeh", "count": 40, "amount": 0.4, "seed": 1},
        {"type": "fog", "amount": 0.26},
        {"type": "light", "amount": 0.12},
    ],
    "aurora": [
        {"type": "breathing_zoom", "amount": 0.08, "orbit": 0.5},
        {"type": "aurora", "amount": 0.7},
        {"type": "particles", "kind": "fireflies", "count": 160, "amount": 0.8, "seed": 3},  # stars
        {"type": "fog", "amount": 0.18},
        {"type": "vignette_pulse", "amount": 0.16},
    ],
    "calm": [  # neutral fallback for anything unmatched
        {"type": "breathing_zoom", "amount": 0.10, "orbit": 0.5},
        {"type": "particles", "kind": "dust", "count": 140, "amount": 0.5, "seed": 11},
        {"type": "fog", "amount": 0.22},
        {"type": "light", "amount": 0.10},
        {"type": "vignette_pulse", "amount": 0.15},
    ],
}

# Keyword → preset, for fast offline matching when no LLM is available.
_PRESET_KEYWORDS = {
    "space": ["space", "cosmic", "star", "nebula", "galaxy", "void", "orbit", "spacecraft", "planet"],
    "rain": ["rain", "storm", "drizzle", "downpour", "wet", "monsoon"],
    "snow": ["snow", "winter", "blizzard", "frost", "arctic"],
    "fireplace": ["fire", "fireplace", "ember", "hearth", "campfire", "candle", "flame"],
    "forest": ["forest", "woods", "jungle", "trees", "meadow", "garden", "dawn", "sunbeam"],
    "ocean": ["ocean", "sea", "beach", "waves", "underwater", "lake", "river", "coast"],
    "aurora": ["aurora", "northern lights", "borealis", "polar", "cosmic"],
}


def preset_for_scene(scene_text: str) -> list[dict]:
    """Pick a motion preset from a free-text scene description via keyword match.
    Use this as the offline fallback; Claude can return a preset name or a custom
    layer list for richer matching."""
    text = (scene_text or "").lower()
    best, best_hits = "calm", 0
    for name, words in _PRESET_KEYWORDS.items():
        hits = sum(1 for w in words if w in text)
        if hits > best_hits:
            best, best_hits = name, hits
    layers = [dict(l) for l in SCENE_PRESETS[best]]

    # Honor a colored-glow cue offline: a color word + a light/glow/alert cue.
    if any(c in text for c in ("light", "glow", "alert", "neon", "lit", "lamp", "console")):
        for cname in _GLOW_COLORS:
            if cname in text:
                layers.append({"type": "color_glow", "amount": 0.28, "color": cname})
                break
    # Region-aware cues (segmented at render time).
    types = {l["type"] for l in layers}
    if any(w in text for w in ("nebula", "gas cloud", "cosmic cloud")) and "nebula" not in types:
        layers.append({"type": "nebula", "amount": 0.5, "region": "sky"})
    if any(w in text for w in ("water", "ocean", "sea", "lake", "river", "waves", "reflection")) \
            and "shimmer" not in types:
        layers.append({"type": "shimmer", "amount": 0.5, "region": "water"})
    return layers


# Validation bounds for each layer param — the director's output is clamped to
# these so a hallucinated value can never break the render or look broken.
_LAYER_SPEC = {
    "breathing_zoom": {"amount": (0.0, 0.25), "orbit": (0.0, 1.0), "pan": (0.0, 1.0)},
    "particles":      {"count": (10, 500), "amount": (0.0, 1.2)},
    "fog":            {"amount": (0.0, 0.5)},
    "light":          {"amount": (0.0, 0.25)},
    "vignette_pulse": {"amount": (0.0, 0.4)},
    "god_rays":       {"amount": (0.0, 0.9), "count": (3, 16),
                       "source_x": (-0.5, 1.5), "source_y": (-0.5, 1.5)},
    "shimmer":        {"amount": (0.0, 1.0), "wavelength": (40.0, 300.0)},
    "aurora":         {"amount": (0.0, 1.0)},
    "parallax":       {"amount": (0.0, 1.0)},
    "color_glow":     {"amount": (0.0, 0.6)},
    "twinkle":        {"amount": (0.0, 1.0), "threshold": (60.0, 240.0)},
    "nebula":         {"amount": (0.0, 1.0)},  # masked slow gas drift (region: sky)
}

# Named colors for the color_glow layer, in BGR (the frame buffer is BGR).
_GLOW_COLORS = {
    "red": (40, 40, 235), "crimson": (40, 30, 210), "orange": (20, 110, 240),
    "amber": (20, 140, 235), "gold": (30, 175, 235), "green": (50, 200, 70),
    "teal": (180, 190, 40), "cyan": (220, 200, 40), "blue": (235, 70, 40),
    "indigo": (200, 60, 70), "purple": (210, 50, 180), "magenta": (190, 40, 220),
    "white": (235, 235, 235), "warm": (60, 150, 240),
}

DIRECTOR_SYSTEM = """You are the motion director for a "living still": ONE image brought \
subtly to life as a calm, hours-long ambient backdrop — think premium living wallpaper, \
NOT an effects demo. The renderer loops it seamlessly; you only choose layers + intensities.

THE GOAL: the image must still look like ITSELF — clean and natural. Effects ENHANCE; they \
must NEVER warp, melt, smear, or distort the actual content. If a choice could look glitchy, \
don't make it. RESTRAINT is the whole skill — a great result is usually a gentle camera move \
plus ONE or TWO quiet touches.

HARD RULES (follow exactly):
1. Use only 2-4 layers. Fewer is better. Do NOT pile effects on "to be safe".
2. At most ONE pixel-MOVING/warping effect total (camera OR parallax OR nebula OR shimmer) — \
never several together, or the image turns to mush.
3. PARALLAX only on real PHOTOGRAPHIC scenes with genuine depth (a photo of a room, a landscape). \
NEVER on illustrated / painted / stylized / CGI / space / sci-fi art — those have no real depth \
and parallax MELTS them. For that art, use breathing_zoom for the camera.
4. breathing_zoom is the primary motion almost every time. Keep amount low; use pan for a glide.

Palette (reply ONLY {"layers":[...]}):
- {"type":"breathing_zoom","amount":0.04-0.10,"orbit":0.2-0.5,"pan":0.0-0.8}  // the camera; pan = lateral glide. Primary motion.
- {"type":"parallax","amount":0.4-0.6}  // PHOTOS with real depth ONLY (rule 3). Replaces breathing_zoom.
- {"type":"nebula","amount":0.3-0.55}  // slow drift of colored gas/clouds (auto-masked to those areas). Nebulae, cosmic gas, clouds.
- {"type":"shimmer","amount":0.3-0.5,"region":"water"}  // ripple ONLY water (oceans/lakes/rivers).
- {"type":"twinkle","amount":0.15-0.35}  // gently flickers the image's OWN bright lights/stars. Keep SUBTLE. Night cities, starfields.
- {"type":"color_glow","amount":0.12-0.28,"color":"amber|gold|red|orange|blue|cyan|teal|green|purple|magenta|white|warm"}  // soft colored light breathing from edges. Use only if the scene has a strong color cast (golden city→amber; red alert→red).
- {"type":"god_rays","amount":0.3-0.6,"count":5-9}  // literal sun shafts ONLY (sun through trees/windows/clouds). NOT space.
- {"type":"aurora","amount":0.4-0.7}  // colored sky curtains; auroras / polar skies only.
- {"type":"particles","kind":"snow|rain|embers|dust|fireflies|bokeh","count":40-250,"amount":0.3-0.6}  // NEW moving specks on top. Only if the scene would truly have them (snowfall, rain, embers). Do NOT add fake stars to an image that already shows stars.
- {"type":"fog","amount":0.12-0.22}  // drifting mist. NEVER in space (reads as clouds in a vacuum).
- {"type":"light","amount":0.05-0.12}  // very subtle global brightness breathing. Safe.
- {"type":"vignette_pulse","amount":0.10-0.16}  // subtle edge darkening. Safe.

EXAMPLES (note how FEW layers):
- Space city with a nebula: breathing_zoom (gentle pan) + nebula + faint twinkle [+ soft color_glow if strongly tinted]. 3-4 layers. NO parallax, NO fog, NO god rays.
- Cozy rainy window: breathing_zoom + rain particles + fog + light.
- Ocean at sunset: breathing_zoom + shimmer(region water) + warm light.

HONOR the scene text: include what it asks for ("red glow" → color_glow red); omit what it says \
no to ("no clouds" → no fog/nebula). Output ONLY the JSON, no prose."""


def _strip_fences(raw: str) -> str:
    clean = (raw or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
    if clean.endswith("```"):
        clean = clean.rsplit("```", 1)[0]
    return clean.strip()


def _validate_layers(layers: list) -> list[dict]:
    """Keep only known layer types, clamp params to safe ranges, coerce numbers."""
    out = []
    for l in layers if isinstance(layers, list) else []:
        if not isinstance(l, dict):
            continue
        t = l.get("type")
        spec = _LAYER_SPEC.get(t)
        if spec is None:
            continue
        clean = {"type": t}
        if t == "particles":
            kind = str(l.get("kind", "dust")).lower().strip()
            clean["kind"] = kind if kind in PARTICLE_PRESETS else "dust"
            if "seed" in l:
                try:
                    clean["seed"] = int(l["seed"])
                except (TypeError, ValueError):
                    pass
        if t == "god_rays" and isinstance(l.get("warm"), bool):
            clean["warm"] = l["warm"]
        if t == "color_glow":
            color = str(l.get("color", "red")).lower().strip()
            clean["color"] = color if color in _GLOW_COLORS else "red"
        if t in ("shimmer", "nebula") and "region" in l:
            region = str(l.get("region", "")).lower().strip()
            if region in ("sky", "water"):
                clean["region"] = region
        for param, (lo, hi) in spec.items():
            if param in l:
                try:
                    v = float(l[param])
                except (TypeError, ValueError):
                    continue
                v = max(lo, min(hi, v))
                clean[param] = int(round(v)) if param == "count" else v
        out.append(clean)
    return out


# Named motion styles for the UI dropdown — predictable looks the user can pick
# instead of leaving it to the director. "auto" = let Claude choose from the scene.
STYLE_PRESETS = {
    "drift": [
        {"type": "breathing_zoom", "amount": 0.08, "orbit": 0.35},
        {"type": "light", "amount": 0.07},
        {"type": "vignette_pulse", "amount": 0.14},
    ],
    "stargaze": [dict(l) for l in SCENE_PRESETS["space"]],
    "parallax": [
        {"type": "parallax", "amount": 0.5},
        {"type": "light", "amount": 0.08},
        {"type": "vignette_pulse", "amount": 0.14},
    ],
    "calm": [dict(l) for l in SCENE_PRESETS["calm"]],
}


def motion_style_preset(name: str) -> list[dict]:
    base = STYLE_PRESETS.get((name or "").lower())
    return [dict(l) for l in (base or SCENE_PRESETS["calm"])]


def scale_motion(layers: list[dict], factor: float) -> list[dict]:
    """Scale motion intensity (amount / orbit / particle count) by a factor, then
    re-clamp to safe ranges. factor < 1 = calmer, > 1 = stronger."""
    out = []
    for l in (layers or []):
        m = dict(l)
        for k in ("amount", "orbit", "pan"):
            if k in m:
                try:
                    m[k] = float(m[k]) * factor
                except (TypeError, ValueError):
                    pass
        if "count" in m:
            try:
                m["count"] = int(round(float(m["count"]) * factor))
            except (TypeError, ValueError):
                pass
        out.append(m)
    return _validate_layers(out)


def choose_layers(scene_text: str, anthropic_key: Optional[str] = None,
                  model: str = "claude-sonnet-4-6") -> tuple[list[dict], str]:
    """Compose motion layers for a scene. Returns (layers, source).

    With an Anthropic key, Claude acts as a motion director and composes a CUSTOM
    layer set from the full palette (handles novel scenes like "misty graveyard at
    dusk"). Output is validated/clamped. Falls back to offline preset matching on
    any error or empty result, so this never blocks rendering.
    """
    if anthropic_key:
        try:
            from anthropic import Anthropic
            import json as _json
            client = Anthropic(api_key=anthropic_key)
            resp = client.messages.create(
                model=model, max_tokens=600, system=DIRECTOR_SYSTEM,
                messages=[{"role": "user", "content": f"Scene: {scene_text}"}],
            )
            data = _json.loads(_strip_fences(resp.content[0].text))
            layers = _validate_layers(data.get("layers", []))
            if layers:
                return layers, "claude:custom"
        except Exception as e:
            print(f"  [motion] director fell back to presets: {e}", flush=True)
    return preset_for_scene(scene_text), "keyword"


def choose_layers_from_image(image_path: str, scene_text: str = "",
                             anthropic_key: Optional[str] = None,
                             model: str = "claude-sonnet-4-6") -> tuple[list[dict], str]:
    """VISION motion director: Claude actually LOOKS at the image and composes the
    motion layers to match what's really there (where the sky/gas, water, bright
    lights, foreground actually are) — instead of guessing from text. This is what
    stops 'fog on a spaceship'. Falls back to the text director, then presets."""
    if anthropic_key:
        try:
            import base64
            import io
            import json as _json
            from anthropic import Anthropic

            im = Image.open(image_path).convert("RGB")
            im.thumbnail((1024, 1024))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            b64 = base64.standard_b64encode(buf.getvalue()).decode()

            client = Anthropic(api_key=anthropic_key)
            resp = client.messages.create(
                model=model, max_tokens=900, system=DIRECTOR_SYSTEM,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text":
                        f"Context (text brief): {scene_text}\n\n"
                        "LOOK AT THIS IMAGE and compose the motion layers that best bring "
                        "IT to life. Match each effect to where things actually are in the "
                        "frame: drift gas/nebula only where you see sky/gas, shimmer only on "
                        "water, twinkle the bright lights you can see, and choose a camera "
                        "move (pan vs zoom) that suits the composition. Subtle, hours-long, "
                        "seamless. Output ONLY the JSON."},
                ]}],
            )
            data = _json.loads(_strip_fences(resp.content[0].text))
            layers = _validate_layers(data.get("layers", []))
            if layers:
                return layers, "claude:vision"
        except Exception as e:
            print(f"  [motion] vision director failed ({e}); using text director", flush=True)
    # Fall back to the text director (which itself falls back to presets).
    return choose_layers(scene_text, anthropic_key=anthropic_key, model=model)


def _find(layers: list[dict], type_name: str) -> Optional[dict]:
    for l in layers:
        if l.get("type") == type_name:
            return l
    return None


def _cover_resize(im: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize+crop to exactly fill target (preserve aspect, crop overflow)."""
    sw, sh = im.size
    scale = max(target_w / sw, target_h / sh)
    rw, rh = int(math.ceil(sw * scale)), int(math.ceil(sh * scale))
    im = im.resize((rw, rh), Image.LANCZOS)
    left = (rw - target_w) // 2
    top = (rh - target_h) // 2
    return im.crop((left, top, left + target_w, top + target_h))


if __name__ == "__main__":
    import sys
    img = sys.argv[1] if len(sys.argv) > 1 else None
    if not img:
        print("usage: python motion_compositor.py <image> [out.mp4]")
        sys.exit(1)
    out = sys.argv[2] if len(sys.argv) > 2 else None
    MotionCompositor().render(img, out, on_status=lambda m: None)
