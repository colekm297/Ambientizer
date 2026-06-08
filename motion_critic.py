"""Gemini motion critic — the automated visual judge for the Living Still engine.

Gemini *watches* a rendered loop (native video understanding) and returns a
structured verdict: is the loop seamless, is the motion natural, are there
artifacts, does it suit the scene, is it good enough to publish? This is the
feedback signal that lets the engine be hardened autonomously: render → judge →
rewrite motion_compositor.py → re-render → repeat until it locks in.

Reuses the project's existing Gemini setup (genai client + types.Part.from_bytes,
same as audio_critic.py / reference_analyzer.py).

CLI:  python motion_critic.py <loop.mp4> [source_image.png]   # judge an existing render
      python motion_critic.py --render <image.png>            # render + judge in one shot
Prints a JSON verdict to stdout.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

from google import genai
from google.genai import types

try:
    from gemini_limiter import gemini_limiter
except Exception:
    gemini_limiter = None

FALLBACK_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.5-flash"]

RUBRIC = """You are a discerning QUALITY critic for AMBIENT "living still" loops — a
single photo brought subtly to life (the real clouds billowing, water shimmering,
lights twinkling, gentle parallax) and tiled to play for an hour on YouTube.

Do NOT just decide whether it's "passable" — assess HOW GOOD it is as a finished
piece, and how to make it better. Hold a high bar: a loop that's technically fine
but flat/lifeless is a 5-6, not a pass. A 10 is something you'd be proud to publish.

Rate each dimension 0-10:
- aliveness:    does the still genuinely come alive and feel compelling, or is it barely moving / dead?
- naturalness:  is the motion gentle, believable, tasteful — not crude, overdone, mechanical, or melting?
- scene_fit:    does it animate the RIGHT elements the RIGHT way? The REAL clouds in the
                photo should drift/billow — NOT a fake cloud overlay rushing past, NOT
                fog on a spaceship. Water shimmers, lights twinkle, etc.
- polish:       free of tearing, ghosting, smearing, warping artifacts, popping?

Return ONLY a JSON object, no prose:
{
  "quality_score": 0-10,                 // overall quality as a finished ambient piece
  "tier": "exceptional|strong|decent|flat|broken",
  "dimensions": {"aliveness": 0-10, "naturalness": 0-10, "scene_fit": 0-10, "polish": 0-10},
  "what_works": ["..."],
  "what_would_elevate_it": ["concrete, engine-level improvements — even if it's already good, what would push it to a 10?"],
  "summary": "one or two sentences"
}

Be a critic pushing for excellence, not a lenient gatekeeper. Your output drives
code changes to the motion engine, so make 'what_would_elevate_it' specific and
actionable. Do NOT judge loop seamlessness — a separate exact pixel check handles
that; focus on the QUALITY and craft of the motion itself."""


def _client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        # the app loads .env; mirror that for standalone CLI use
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.environ.get("GEMINI_API_KEY")
        except Exception:
            pass
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set (check .env)")
    return genai.Client(api_key=key)


def measure_loop_objective(video_path: str) -> dict:
    """Exact, Gemini-independent measurements: loop seamlessness (frame-0 vs last
    frame) and motion magnitude (frame-0 vs mid frame). These are the objective
    gates — Gemini's eye for seams proved unreliable (false-passes AND false-fails),
    so the math decides seamlessness, not the model."""
    import subprocess, tempfile
    import numpy as np
    from PIL import Image
    FF = "/opt/homebrew/bin/ffmpeg"
    def frame_at(spec_args, out):
        subprocess.run([FF, "-y", *spec_args, "-update", "1", out],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return np.asarray(Image.open(out).convert("RGB"), dtype=np.float32)
    with tempfile.TemporaryDirectory() as d:
        import os as _os
        f0 = frame_at(["-i", video_path, "-vf", "select=eq(n\\,0)", "-vframes", "1"], _os.path.join(d, "a.png"))
        fl = frame_at(["-sseof", "-0.06", "-i", video_path], _os.path.join(d, "z.png"))
        fm = frame_at(["-ss", "00:00:04", "-i", video_path, "-vframes", "1"], _os.path.join(d, "m.png"))
    seam = float(np.abs(f0 - fl).mean())
    motion = float(np.abs(f0 - fm).mean())
    return {
        "seam_diff": round(seam, 2),
        "loop_seamless": seam < 6.0,          # measured threshold; hard jumps are 20-100+
        "motion_magnitude": round(motion, 2),
        "has_motion": motion > 0.8,           # below this it's basically static
    }


def critique_loop(video_path: str, source_image: Optional[str] = None) -> dict:
    """Objective gates (seam + motion, exact) + Gemini quality review (subjective)."""
    objective = measure_loop_objective(video_path)
    client = _client()
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    parts = [types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")]
    if source_image:
        with open(source_image, "rb") as f:
            parts.append(types.Part.from_bytes(data=f.read(), mime_type="image/png"))
        parts.append(types.Part(text="(The second image is the ORIGINAL still — judge whether the motion respects and suits it.)"))
    parts.append(types.Part(text=RUBRIC))

    last_error = None
    for model in FALLBACK_MODELS:
        for attempt in range(1, 4):
            if gemini_limiter and not gemini_limiter.wait_if_needed(timeout=90):
                raise RuntimeError("Gemini rate limit reached.")
            try:
                if gemini_limiter:
                    gemini_limiter.record_call(f"motion_critic:{model}")
                resp = client.models.generate_content(model=model, contents=parts)
                text = (resp.text or "").strip()
                # tolerate ```json fences
                if text.startswith("```"):
                    text = text.split("```", 2)[1].lstrip("json").strip("` \n")
                quality = json.loads(text)
                qs = float(quality.get("quality_score", 0))
                # Combined verdict: math gates the objective stuff, Gemini grades quality.
                ship_ready = (objective["loop_seamless"] and objective["has_motion"]
                              and qs >= 8.0)
                return {
                    "ship_ready": ship_ready,        # passes objective gates AND high quality
                    "quality_score": qs,
                    "objective": objective,          # seam + motion, exact (trust these)
                    "quality": quality,              # Gemini's graded review (subjective)
                }
            except json.JSONDecodeError as e:
                last_error = f"non-JSON from {model}: {text[:200]}"
            except Exception as e:
                err = str(e)
                last_error = f"{type(e).__name__}: {err[:150]}"
                if ("429" in err or "RESOURCE_EXHAUSTED" in err) and gemini_limiter and attempt < 3:
                    time.sleep(gemini_limiter.handle_429(attempt)); continue
                break  # try next model
    raise RuntimeError(f"Gemini motion critique failed: {last_error}")


def render_and_critique(image_path: str, loop_sec: float = 8.0,
                        size: tuple[int, int] = (1280, 720)) -> dict:
    """Auto-plan motion for an image, render a loop, and judge it. Returns
    {"video": path, "verdict": {...}, "layers": [...]}."""
    import motion_compositor as mc
    out = os.path.splitext(image_path)[0] + "_qcloop.mp4"
    layers = None
    try:
        # choose_layers_from_image returns (layers, source_label)
        result = mc.choose_layers_from_image(
            image_path, "", os.environ.get("ANTHROPIC_API_KEY"))
        layers = result[0] if isinstance(result, tuple) else result
        if not (isinstance(layers, list) and all(isinstance(l, dict) for l in layers)):
            layers = None
    except Exception:
        layers = None  # render() falls back to its own default/auto plan
    comp = mc.MotionCompositor()
    video = comp.render(image_path, output_path=out, layers=layers,
                        loop_sec=loop_sec, size=size)
    verdict = critique_loop(video, source_image=image_path)
    return {"video": video, "verdict": verdict, "layers": layers}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--render":
        result = render_and_critique(args[1])
        print(json.dumps(result["verdict"], indent=2))
        print(f"\n[rendered: {result['video']}]", file=sys.stderr)
    else:
        video = args[0]
        src = args[1] if len(args) > 1 else None
        print(json.dumps(critique_loop(video, src), indent=2))
