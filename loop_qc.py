"""loop_qc.py — zero-SDK loop conditioning, blending, and seam verification.

Extracted from fal_loop.py so any visual backend (Google Flow, Veo 3.1,
Gemini Omni, or local ffmpeg clips) can share the same frame prep,
cross-dissolve wrap blend, texture leveling, and seam_report metrics
without importing fal_client.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter


def prep_frame(src: str, dst: str, height: int = 720) -> str:
    """Center-crop to exactly 16:9 and downscale."""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    target = 16 / 9
    if w / h > target:
        new_w = int(round(h * target))
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))
    elif w / h < target:
        new_h = int(round(w / target))
        top = (h - new_h) // 2
        im = im.crop((0, top, w, top + new_h))
    im = im.resize((int(round(height * target / 2)) * 2, height), Image.LANCZOS)
    im.save(dst, quality=95)
    return dst


def last_frame(video: str, dst: str) -> str:
    """Pull the true final frame using -sseof without decoding the whole file."""
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.5", "-i", video, "-update", "1", "-q:v", "2", dst],
        check=True,
        capture_output=True,
    )
    return dst


def _frames(video: str, out_dir: str, fps: Optional[float] = None) -> list[str]:
    pattern = os.path.join(out_dir, "f_%05d.png")
    cmd = ["ffmpeg", "-y", "-i", video]
    if fps:
        cmd += ["-vf", f"fps={fps}"]
    cmd += [pattern]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("f_")
    )


def _duration(video: str) -> float:
    return float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def concat(leg_a: str, leg_b: str, dst: str, blend: float = 0.5) -> str:
    """Join two loop legs with an optional xfade cross-dissolve (never stream-copy)."""
    if blend <= 0:
        filt = "[0:v][1:v]concat=n=2:v=1:a=0[v]"
    else:
        dur_a = _duration(leg_a)
        filt = f"[0:v][1:v]xfade=transition=fade:duration={blend}:offset={dur_a - blend}[v]"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", leg_a, "-i", leg_b,
            "-filter_complex", filt,
            "-map", "[v]", "-an",
            "-c:v", "libx264", "-crf", "17", "-preset", "slow",
            "-pix_fmt", "yuv420p", dst,
        ],
        check=True,
        capture_output=True,
    )
    return dst


def wrap_blend(video: str, dst: str, seconds: float = 0.8) -> str:
    """Fold the clip's own tail over its head so the wrap point disappears."""
    dur = _duration(video)
    n, end = seconds, dur - seconds
    if end <= n:
        raise ValueError(f"clip duration ({dur:.2f}s) too short for wrap_blend({seconds}s)")
    filt = (
        f"[0:v]trim=0:{n},setpts=PTS-STARTPTS[head];"
        f"[1:v]trim={n}:{end},setpts=PTS-STARTPTS[body];"
        f"[2:v]trim={end}:{dur},setpts=PTS-STARTPTS[tail];"
        f"[tail][head]xfade=transition=fade:duration={n}:offset=0[join];"
        f"[join][body]concat=n=2:v=1[v]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video, "-i", video, "-i", video,
            "-filter_complex", filt, "-map", "[v]", "-an",
            "-c:v", "libx264", "-crf", "17", "-preset", "slow",
            "-pix_fmt", "yuv420p", dst,
        ],
        check=True,
        capture_output=True,
    )
    return dst


def _detail(arr: np.ndarray) -> float:
    """Mean gradient magnitude — measures fine spatial texture."""
    return float((np.abs(np.diff(arr, axis=1)).mean() + np.abs(np.diff(arr, axis=0)).mean()) / 2)


def _smooth(xs: list[float], window: int) -> list[float]:
    """Boxcar smoothing for frame-to-frame motion speed envelope."""
    if window <= 1 or len(xs) < window:
        return list(xs)
    a = np.asarray(xs, dtype=np.float64)
    return list(np.convolve(a, np.ones(window) / window, mode="valid"))


def leg_detail(video: str, samples: int = 12) -> float:
    """Mean detail across a clip, sampled evenly."""
    tmp = tempfile.mkdtemp(prefix="detail_")
    try:
        paths = _frames(video, tmp, fps=2)
        if not paths:
            return 0.0
        step = max(1, len(paths) // samples)
        arrs = [np.asarray(Image.open(p).convert("L"), dtype=np.float32) for p in paths[::step]]
        return float(np.mean([_detail(a) for a in arrs]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def match_legs(leg_a: str, leg_b: str, out_dir: str, tolerance: float = 0.12) -> tuple[str, str, dict]:
    """Blur the sharper leg down until both legs carry matching texture."""
    da, db = leg_detail(leg_a), leg_detail(leg_b)
    lo, hi = (da, db) if da <= db else (db, da)
    mismatch = (hi / max(lo, 1e-6)) - 1.0
    info = {
        "detail_a": round(da, 2),
        "detail_b": round(db, 2),
        "mismatch": round(mismatch, 3),
        "corrected": False,
    }
    if mismatch <= tolerance:
        return leg_a, leg_b, info

    sharper, target = (leg_b, da) if db > da else (leg_a, db)
    lo_s, hi_s, best = 0.0, 2.0, None
    probe = os.path.join(out_dir, "_probe.mp4")
    for _ in range(7):
        mid = (lo_s + hi_s) / 2
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", sharper,
                "-vf", f"gblur=sigma={mid:.3f}", "-c:v", "libx264", "-crf", "17",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", probe,
            ],
            check=True,
            capture_output=True,
        )
        d = leg_detail(probe)
        best = mid
        if d > target:
            lo_s = mid
        else:
            hi_s = mid
    if os.path.exists(probe):
        os.remove(probe)

    dst = os.path.join(out_dir, "leg_b_matched.mp4" if sharper == leg_b else "leg_a_matched.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", sharper,
            "-vf", f"gblur=sigma={best:.3f}", "-c:v", "libx264", "-crf", "17",
            "-preset", "slow", "-pix_fmt", "yuv420p", "-an", dst,
        ],
        check=True,
        capture_output=True,
    )
    info.update(corrected=True, sigma=round(best, 3), detail_after=round(leg_detail(dst), 2))
    if sharper == leg_b:
        return leg_a, dst, info
    return dst, leg_b, info


def flatten_detail(video: str, dst: str, percentile: float = 3.0, fps: int = 24) -> dict:
    """Hold texture constant across a loop cell, frame by frame."""
    tmp = tempfile.mkdtemp(prefix="flat_")
    out_dir = tempfile.mkdtemp(prefix="flatout_")
    try:
        paths = _frames(video, tmp, fps=fps)
        arrs = [np.asarray(Image.open(p).convert("L"), dtype=np.float32) for p in paths]
        dets = np.array([_detail(a) for a in arrs])
        target = float(np.percentile(dets, percentile))
        before = float((dets.max() - dets.min()) / max(dets.min(), 1e-6))

        for i, p in enumerate(paths):
            im = Image.open(p)
            if dets[i] <= target * 1.02:
                im.save(os.path.join(out_dir, f"f_{i:05d}.png"))
                continue
            lo, hi = 0.0, 2.5
            for _ in range(6):
                mid = (lo + hi) / 2
                probe = im.filter(ImageFilter.GaussianBlur(radius=mid))
                d = _detail(np.asarray(probe.convert("L"), dtype=np.float32))
                if d > target:
                    lo = mid
                else:
                    hi = mid
            im.filter(ImageFilter.GaussianBlur(radius=(lo + hi) / 2)).save(
                os.path.join(out_dir, f"f_{i:05d}.png")
            )

        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-framerate", str(fps),
                "-i", os.path.join(out_dir, "f_%05d.png"),
                "-c:v", "libx264", "-crf", "17", "-preset", "slow",
                "-pix_fmt", "yuv420p", "-an", dst,
            ],
            check=True,
            capture_output=True,
        )
        return {
            "target": round(target, 2),
            "swing_before": round(before, 2),
            "swing_after": round(seam_report(dst)["detail_swing"], 2),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)


def seam_report(video: str, source_frame: Optional[str] = None) -> dict:
    """Measure loop wrap, junction spike, detail swing, speed envelope, and drift."""
    tmp = tempfile.mkdtemp(prefix="seam_")
    try:
        paths = _frames(video, tmp, fps=8)
        arrs = [np.asarray(Image.open(p).convert("L"), dtype=np.float32) for p in paths]
        if len(arrs) < 3:
            return {"error": f"only {len(arrs)} frames decoded"}
        wrap = float(np.mean(np.abs(arrs[-1] - arrs[0])))
        deltas = [float(np.mean(np.abs(arrs[i + 1] - arrs[i]))) for i in range(len(arrs) - 1)]
        motion = float(np.mean(deltas))
        dets = [_detail(a) for a in arrs]
        env = _smooth(deltas, 3)
        out = {
            "frames_sampled": len(arrs),
            "wrap": round(wrap, 2),
            "wrap_ratio": round(wrap / max(motion, 1e-6), 2),
            "motion_mean": round(motion, 2),
            "motion_max": round(float(np.max(deltas)), 2),
            "junction_spike": round(float(np.max(deltas) / max(np.mean(deltas), 1e-6)), 2),
            "detail_swing": round((max(dets) - min(dets)) / max(min(dets), 1e-6), 2),
        }
        out["detail_ok"] = bool(out["detail_swing"] < 0.20)
        out["speed_envelope"] = round(float(max(env) / max(min(env), 1e-6)), 2)
        out["speed_ok"] = bool(out["speed_envelope"] < 1.35)
        if source_frame:
            src = np.asarray(
                Image.open(source_frame).convert("L").resize((arrs[0].shape[1], arrs[0].shape[0])),
                dtype=np.float32,
            )
            out["drift"] = round(float(np.mean(np.abs(arrs[-1] - src))), 2)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def passes_draft_gate(report: dict, max_junction: float = 1.9, max_wrap: float = 5.5) -> bool:
    """True when a loop passes the calibrated living-still seam gate."""
    if "error" in report:
        return False
    return (
        float(report.get("junction_spike", 99.0)) <= max_junction
        and float(report.get("wrap", 99.0)) <= max_wrap
    )


def finalize_loop(
    video: str,
    dst: str,
    source_frame: Optional[str] = None,
    blend_seconds: float = 0.8,
    flatten: bool = False,
) -> dict:
    """Strip audio, optionally apply wrap_blend + flatten_detail, and return seam_report."""
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="loopfin_")
    try:
        cur = os.path.join(tmp_dir, "noaudio.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", video, "-an", "-c:v", "copy", cur],
            check=True,
            capture_output=True,
        )
        dur = _duration(cur)
        if blend_seconds > 0 and dur > blend_seconds + 2.0:
            blended = os.path.join(tmp_dir, "blended.mp4")
            wrap_blend(cur, blended, seconds=blend_seconds)
            cur = blended
        if flatten:
            flat_out = os.path.join(tmp_dir, "flat.mp4")
            flatten_detail(cur, flat_out)
            cur = flat_out
        shutil.copy2(cur, dst)
        return seam_report(dst, source_frame=source_frame)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
