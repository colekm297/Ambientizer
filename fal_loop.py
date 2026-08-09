"""fal_loop.py — seamless AI-generated loops via the two-leg trick.

The procedural living-still engine can only move pixels that already exist, so
cloth and hair never fill or lift; they slide. A video model invents new pixels,
but every hosted model refuses to loop: hand it the same image as first and last
frame and the cheapest way to satisfy that constraint is to not move at all.
The endpoint constraint lives in latent space, the prompt is only a suggestion,
so the render collapses to a still. That is the wall this module walks around.

Two legs, neither one with matching endpoints:

    leg A   start = the still, no end frame        -> real, unconstrained motion
    leg B   start = A's last frame, end = the still -> a genuine journey back

Concatenated, the pair starts and ends on the same image, so it tiles forever
with no crossfade and no boomerang ([[feedback-never-boomerang]] applies here
too: leg B must be a new generation, never leg A reversed).

    from fal_loop import generate_loop
    result = generate_loop("inputs/sirens_final.png", MOTION_PROMPT)
    print(result["loop"], result["seam"])

Cost is real money, so every entry point prints its estimate first and
--dry-run stops before spending anything.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))

# Veo 3.1 Lite is the cheapest pair of endpoints where BOTH halves of the trick
# exist under one model, which matters: leg B inherits leg A's final frame, and
# a style change at the junction is visible even when the geometry matches.
# $0.03/sec at 720p with audio off. An 8s + 8s loop is $0.48.
LEG_A_ENDPOINT = "fal-ai/veo3.1/lite/image-to-video"
LEG_B_ENDPOINT = "fal-ai/veo3.1/lite/first-last-frame-to-video"
PRICE_PER_SECOND = {"720p": 0.03, "1080p": 0.05}  # audio off; on is ~1.7x
LEG_B_SECONDS = 8  # the flf endpoint is fixed at 8s, it takes no duration

# Ambient scenes want a locked-off camera. Veo's default instinct is to push in
# or drift, and a moving camera makes a loop impossible no matter how clean the
# endpoints are, so this rides on every request unless overridden.
DEFAULT_NEGATIVE = (
    "camera movement, camera pan, camera zoom, dolly, handheld shake, "
    "scene change, cut, transition, text, watermark, people walking, "
    "new characters entering frame"
)


# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------


def _load_key() -> str:
    """FAL_KEY out of the environment or .env. Never printed, never logged."""
    key = os.environ.get("FAL_KEY")
    if not key:
        try:
            from dotenv import load_dotenv

            load_dotenv(os.path.join(HERE, ".env"))
        except ImportError:
            pass
        key = os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError(
            "No FAL_KEY. Add `FAL_KEY=...` to .env (fal.ai -> Settings -> API Keys)."
        )
    os.environ["FAL_KEY"] = key
    return key


def _fal():
    _load_key()
    import fal_client

    return fal_client


# -----------------------------------------------------------------------------
# Frames
# -----------------------------------------------------------------------------


def prep_frame(src: str, dst: str, height: int = 720) -> str:
    """Center-crop to exactly 16:9 and downscale.

    Veo takes 8MB max and wants 16:9; the Midjourney stills are 2912x1632,
    which is 1.784:1, close enough to look right and wrong enough that the
    model letterboxes it if you send it raw.
    """
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
    """Pull the true final frame. `-sseof` seeks from the end without decoding
    the whole file, and `-update 1` keeps overwriting so the last one wins."""
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.5", "-i", video,
         "-update", "1", "-q:v", "2", dst],
        check=True, capture_output=True,
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


# -----------------------------------------------------------------------------
# Generation
# -----------------------------------------------------------------------------


def _run(endpoint: str, payload: dict, label: str) -> str:
    fal_client = _fal()
    t0 = time.time()

    def _log(update):
        for entry in getattr(update, "logs", None) or []:
            msg = entry.get("message", "").strip()
            if msg:
                print(f"    [{label}] {msg}")

    result = fal_client.subscribe(
        endpoint, arguments=payload, with_logs=True, on_queue_update=_log
    )
    print(f"    [{label}] done in {time.time() - t0:.0f}s")
    url = result["video"]["url"]
    return url


def _download(url: str, dst: str) -> str:
    import requests

    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dst, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    return dst


def concat(leg_a: str, leg_b: str, dst: str) -> str:
    """Re-encode rather than stream-copy: the two legs come back from separate
    generations and a copy-concat inherits whichever GOP structure came first,
    which is what makes a 'seamless' file stutter at the junction."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", leg_a, "-i", leg_b,
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
         "-map", "[v]", "-an",
         "-c:v", "libx264", "-crf", "17", "-preset", "slow",
         "-pix_fmt", "yuv420p", dst],
        check=True, capture_output=True,
    )
    return dst


def wrap_blend(video: str, dst: str, seconds: float = 0.8) -> str:
    """Fold the clip's own tail over its head so the wrap point disappears.

    Leg B lands on the original framing, but the WATER cannot match: a
    generative model has no periodic function underneath it, so the wave
    pattern at the last frame is simply a different wave pattern. That residual
    is what pops when the file tiles.

    This is not a boomerang and not a reverse — time still runs one direction
    throughout. The tail is composited over the head with a rising alpha, so
    the file's own end is already visible as its beginning fades in, and the
    join has nothing left to reveal. Output is `seconds` shorter than input.
    """
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", video],
        check=True, capture_output=True, text=True).stdout.strip())
    n, end = seconds, dur - seconds
    filt = (
        f"[0:v]trim=0:{n},setpts=PTS-STARTPTS[head];"
        f"[1:v]trim={n}:{end},setpts=PTS-STARTPTS[body];"
        f"[2:v]trim={end}:{dur},setpts=PTS-STARTPTS[tail];"
        f"[tail][head]xfade=transition=fade:duration={n}:offset=0[join];"
        f"[join][body]concat=n=2:v=1[v]"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", video, "-i", video, "-i", video,
         "-filter_complex", filt, "-map", "[v]", "-an",
         "-c:v", "libx264", "-crf", "17", "-preset", "slow",
         "-pix_fmt", "yuv420p", dst],
        check=True, capture_output=True,
    )
    return dst


# -----------------------------------------------------------------------------
# Verification
# -----------------------------------------------------------------------------


def seam_report(video: str, source_frame: Optional[str] = None) -> dict:
    """Measure the two things that can be wrong with a two-leg loop.

    `wrap` is last frame vs first frame — how visible the cut is when it tiles.
    `drift` is last frame vs the ORIGINAL still, which catches leg B landing
    somewhere plausible but not home. Both are mean absolute brightness delta on
    0-255. Under ~2 reads as clean, over ~6 is a visible pop.
    `motion` is the average frame-to-frame delta, the check that the whole
    thing did not collapse into a still (the failure mode this module exists
    to avoid) — under ~0.5 means nothing moved.
    """
    tmp = tempfile.mkdtemp(prefix="seam_")
    try:
        paths = _frames(video, tmp, fps=8)
        arrs = [np.asarray(Image.open(p).convert("L"), dtype=np.float32) for p in paths]
        if len(arrs) < 3:
            return {"error": f"only {len(arrs)} frames decoded"}
        wrap = float(np.mean(np.abs(arrs[-1] - arrs[0])))
        deltas = [float(np.mean(np.abs(arrs[i + 1] - arrs[i]))) for i in range(len(arrs) - 1)]
        out = {
            "frames_sampled": len(arrs),
            "wrap": round(wrap, 2),
            "motion_mean": round(float(np.mean(deltas)), 2),
            "motion_max": round(float(np.max(deltas)), 2),
            "junction_spike": round(float(np.max(deltas) / max(np.mean(deltas), 1e-6)), 2),
        }
        if source_frame:
            src = np.asarray(
                Image.open(source_frame).convert("L").resize(
                    (arrs[0].shape[1], arrs[0].shape[0])
                ),
                dtype=np.float32,
            )
            out["drift"] = round(float(np.mean(np.abs(arrs[-1] - src))), 2)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -----------------------------------------------------------------------------
# The loop
# -----------------------------------------------------------------------------


def estimate_cost(leg_a_seconds: int, resolution: str) -> float:
    rate = PRICE_PER_SECOND[resolution]
    return round((leg_a_seconds + LEG_B_SECONDS) * rate, 2)


def generate_loop(
    image: str,
    prompt: str,
    out_dir: str = "output/fal_loops",
    name: Optional[str] = None,
    leg_a_seconds: int = 8,
    resolution: str = "720p",
    return_prompt: Optional[str] = None,
    negative_prompt: str = DEFAULT_NEGATIVE,
    seed: Optional[int] = None,
    keep_legs: bool = True,
    blend_seconds: float = 0.8,
    dry_run: bool = False,
) -> dict:
    """Build one seamless loop. Returns paths + the seam report."""
    name = name or os.path.splitext(os.path.basename(image))[0]
    out_dir = os.path.join(HERE, out_dir, name)
    os.makedirs(out_dir, exist_ok=True)

    cost = estimate_cost(leg_a_seconds, resolution)
    total_seconds = leg_a_seconds + LEG_B_SECONDS
    print(f"  {name}: {leg_a_seconds}s + {LEG_B_SECONDS}s = {total_seconds}s loop, "
          f"{resolution}, about ${cost:.2f}")
    if dry_run:
        return {"dry_run": True, "estimated_cost": cost}

    fal_client = _fal()

    start_png = prep_frame(image, os.path.join(out_dir, "start.png"),
                           height=720 if resolution == "720p" else 1080)
    start_url = fal_client.upload_file(start_png)

    # Leg A: no end frame at all. This is the generation that is allowed to
    # actually move, so it carries the full motion prompt.
    print("  leg A: free motion from the still")
    a_payload = {
        "prompt": prompt,
        "image_url": start_url,
        "duration": f"{leg_a_seconds}s",
        "resolution": resolution,
        "aspect_ratio": "16:9",
        "generate_audio": False,
        "negative_prompt": negative_prompt,
    }
    if seed is not None:
        a_payload["seed"] = seed
    leg_a = _download(_run(LEG_A_ENDPOINT, a_payload, "A"),
                      os.path.join(out_dir, "leg_a.mp4"))

    # Leg B: start somewhere real, end at home. Endpoints differ, so the model
    # has no incentive to freeze — that is the whole trick.
    print("  leg B: return to the opening frame")
    a_last = last_frame(leg_a, os.path.join(out_dir, "leg_a_last.png"))
    b_payload = {
        "prompt": return_prompt or prompt,
        "first_frame_url": fal_client.upload_file(a_last),
        "last_frame_url": start_url,
        "resolution": resolution,
        "aspect_ratio": "16:9",
        "generate_audio": False,
        "negative_prompt": negative_prompt,
    }
    if seed is not None:
        b_payload["seed"] = seed + 1
    leg_b = _download(_run(LEG_B_ENDPOINT, b_payload, "B"),
                      os.path.join(out_dir, "leg_b.mp4"))

    raw = concat(leg_a, leg_b, os.path.join(out_dir, f"{name}_raw.mp4"))
    loop = raw
    if blend_seconds:
        loop = wrap_blend(raw, os.path.join(out_dir, f"{name}_loop.mp4"),
                          seconds=blend_seconds)
    report = seam_report(loop, source_frame=start_png)
    report["raw_wrap"] = seam_report(raw)["wrap"]
    report["estimated_cost"] = cost
    report["seconds"] = total_seconds

    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump({"prompt": prompt, "return_prompt": return_prompt,
                   "negative_prompt": negative_prompt, "seed": seed,
                   "report": report}, fh, indent=2)

    if not keep_legs:
        for path in (leg_a, leg_b):
            os.remove(path)

    print(f"  loop: {loop}")
    print(f"  seam: {json.dumps(report)}")
    return {"loop": loop, "leg_a": leg_a, "leg_b": leg_b,
            "start": start_png, "seam": report}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--return-prompt", default=None,
                    help="prompt for leg B; defaults to the same motion prompt")
    ap.add_argument("--name", default=None)
    ap.add_argument("--seconds", type=int, default=8, choices=[4, 6, 8],
                    help="leg A length; leg B is always 8s")
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="output/fal_loops")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    generate_loop(
        args.image, args.prompt, out_dir=args.out, name=args.name,
        leg_a_seconds=args.seconds, resolution=args.resolution,
        return_prompt=args.return_prompt, seed=args.seed, dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
