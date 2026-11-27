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
import time
from typing import Optional

from loop_qc import (  # noqa: F401 — re-exported for legacy callers
    _detail,
    _frames,
    _smooth,
    concat,
    flatten_detail,
    last_frame,
    leg_detail,
    match_legs,
    prep_frame,
    seam_report,
    wrap_blend,
)

HERE = os.path.dirname(os.path.abspath(__file__))

# Lite is the budget tier and it shows: its two endpoints render texture 48-57%
# apart at 1080p, which costs a rework every time. A dollar that works every time beats
# fifty cents and six reworks.
MODELS = {
    "lite": {
        "leg_a": "fal-ai/veo3.1/lite/image-to-video",
        "leg_b": "fal-ai/veo3.1/lite/first-last-frame-to-video",
        "price": {"720p": 0.03, "1080p": 0.05},
    },
    "full": {
        "leg_a": "fal-ai/veo3.1/image-to-video",
        "leg_b": "fal-ai/veo3.1/first-last-frame-to-video",
        "price": {"720p": 0.20, "1080p": 0.20},
    },
}
DEFAULT_MODEL = "full"

LEG_A_ENDPOINT = MODELS["lite"]["leg_a"]   # kept for callers that import these
LEG_B_ENDPOINT = MODELS["lite"]["leg_b"]
PRICE_PER_SECOND = MODELS["lite"]["price"]  # audio off; on is ~1.7x
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


# Frame prep, blending, and seam verification now live in loop_qc.py (re-exported above).


# -----------------------------------------------------------------------------
# The loop (legacy fal.ai path)
# -----------------------------------------------------------------------------


def estimate_cost(leg_a_seconds: int, resolution: str,
                  model: str = DEFAULT_MODEL) -> float:
    rate = MODELS[model]["price"][resolution]
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
    model: str = DEFAULT_MODEL,
    keep_legs: bool = True,
    blend_seconds: float = 0.8,
    dry_run: bool = False,
) -> dict:
    """Build one seamless loop. Returns paths + the seam report."""
    name = name or os.path.splitext(os.path.basename(image))[0]
    out_dir = os.path.join(HERE, out_dir, name)
    os.makedirs(out_dir, exist_ok=True)

    endpoints = MODELS[model]
    cost = estimate_cost(leg_a_seconds, resolution, model)
    total_seconds = leg_a_seconds + LEG_B_SECONDS
    print(f"  {name}: {leg_a_seconds}s + {LEG_B_SECONDS}s = {total_seconds}s loop, "
          f"{resolution}, veo3.1 {model}, about ${cost:.2f}")
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
    leg_a = _download(_run(endpoints["leg_a"], a_payload, "A"),
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
    leg_b = _download(_run(endpoints["leg_b"], b_payload, "B"),
                      os.path.join(out_dir, "leg_b.mp4"))

    # Match the legs BEFORE joining them. Skipping this is what put a texture
    # switch every 11 seconds into three hours of the Sirens release.
    use_a, use_b, match = match_legs(leg_a, leg_b, out_dir)
    if match["corrected"]:
        print(f"  legs mismatched by {match['mismatch']:.0%} — blurred the "
              f"sharper one (sigma {match['sigma']}) to {match['detail_after']}")
    else:
        print(f"  legs agree within {match['mismatch']:.0%}, no correction")

    raw = concat(use_a, use_b, os.path.join(out_dir, f"{name}_raw.mp4"))
    loop = raw
    if blend_seconds:
        loop = wrap_blend(raw, os.path.join(out_dir, f"{name}_loop.mp4"),
                          seconds=blend_seconds)
    report = seam_report(loop, source_frame=start_png)
    report["raw_wrap"] = seam_report(raw)["wrap"]
    report["legs"] = match
    report["estimated_cost"] = cost
    report["seconds"] = total_seconds

    if not report.get("detail_ok", True):
        print(f"  WARNING detail_swing {report['detail_swing']} — this loop "
              f"will pulse when tiled. Do NOT build a long-form file from it.")

    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump({"prompt": prompt, "return_prompt": return_prompt,
                   "negative_prompt": negative_prompt, "seed": seed, "model": model,
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
